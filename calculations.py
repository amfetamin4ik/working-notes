"""Read-only models of the supplied Colonization KLT SDK, not a game mod.

Python 3, standard library only. Run normally for numerical checks.
--verify-sources also reads manifest files and compares SHA256 hashes.
No game process, saved game, game file or network service is modified.
"""
from fractions import Fraction
from functools import lru_cache
from pathlib import Path
import argparse
import hashlib
import json
import sys


def trunc_div(a, b):
    """C++ integer division, toward zero, including a negative numerator."""
    if b == 0:
        raise ZeroDivisionError()
    return (-1 if (a < 0) != (b < 0) else 1) * (abs(a) // abs(b))


def rebel_latency(population, bells, target=50, initial=None, weight=10):
    """Exact fixed-input recurrence, one value per city; source model only.

    This does not endorse using uncapped city sentiment in an assessment.
    Actual play has changing population, output, health and city modifiers.
    """
    if population < 1 or weight < 1 or not bells or any(b < 0 for b in bells):
        raise ValueError('Positive population/weight and nonnegative city bells required')
    state = tuple(initial if initial is not None else [0] * len(bells))
    if len(state) != len(bells) or any(r < 0 for r in state):
        raise ValueError('Initial city sentiments do not match')
    for turn in range(100001):
        if sum(state) >= target * population:
            return {'turns': turn, 'sentiments': list(state), 'reached': True}
        following = tuple(((weight - 1) * r + 25 * b) // weight
                          for r, b in zip(state, bells))
        if following == state:
            return {'turns': None, 'sentiments': list(state), 'reached': False}
        state = following
    raise RuntimeError('Iteration bound reached')


def combat_odds(p_attacker, hits_to_kill_defender, hits_to_kill_attacker, rounds=7):
    """Exact probabilities of kill/death/draw without withdrawal or evasion."""
    p = Fraction(p_attacker)
    if not 0 <= p <= 1 or min(hits_to_kill_defender, hits_to_kill_attacker) < 1:
        raise ValueError('Invalid probability or hits')

    @lru_cache(None)
    def solve(t, i, j):
        if i >= hits_to_kill_defender:
            return Fraction(1), Fraction(0), Fraction(0)
        if j >= hits_to_kill_attacker:
            return Fraction(0), Fraction(1), Fraction(0)
        if t >= rounds:
            return Fraction(0), Fraction(0), Fraction(1)
        left, right = solve(t + 1, i + 1, j), solve(t + 1, i, j + 1)
        return tuple(p * a + (1 - p) * b for a, b in zip(left, right))
    return solve(0, 0, 0)


def strength(base, modifier=0, hp=100):
    if base < 1 or not 1 <= hp <= 100:
        raise ValueError('Positive base and 1..100 HP required')
    maximum = max(1, base * (100 + modifier) if modifier > 0
                  else trunc_div(base * 10000, 100 - modifier))
    current = maximum * hp // 100
    return maximum, current, (maximum + current + 1) // 2


def combat_from_strengths(base_a, base_d, mod_a=0, mod_d=0, hp_a=100, hp_d=100):
    _, sa, fa = strength(base_a, mod_a, hp_a)
    _, sd, fd = strength(base_d, mod_d, hp_d)
    p = Fraction(1000 - (1000 * sd // (sa + sd)), 1000)
    fm = (fa + fd + 1) // 2
    damage_a = max(1, 20 * (fd + fm) // (fa + fm))
    damage_d = max(1, 20 * (fa + fm) // (fd + fm))
    hits_a = (hp_d + damage_d - 1) // damage_d
    hits_d = (hp_a + damage_a - 1) // damage_a
    odds = combat_odds(p, hits_a, hits_d)
    return {'round_p_attacker': str(p), 'damage_to_attacker': damage_a,
            'damage_to_defender': damage_d, 'hits_needed_a': hits_a,
            'hits_needed_d': hits_d,
            'kill': str(odds[0]), 'death': str(odds[1]), 'draw': str(odds[2]),
            'kill_percent': float(odds[0] * 100),
            'draw_percent': float(odds[2] * 100)}


def calendar(turn):
    if turn < 0:
        raise ValueError('Turn must be nonnegative')
    left, month = turn, 1492 * 12
    for count, increment in [(100, 12), (80, 9), (80, 6), (40, 3)]:
        used = min(left, count)
        month += used * increment
        left -= used
    month += left * 3
    return {'year': month // 12, 'month': 1 + month % 12}


def father_modifier(percentages=(110, 130, 160, 100, 100)):
    result = 100
    for percentage in percentages:
        result = result * percentage // 100
    return result


def army_cost(infantry, cavalry, artillery, smith=False):
    total = 0
    for count, base, step in [(infantry, 2400, 50), (cavalry, 3600, 180),
                              (artillery, 2000, 100)]:
        for prior in range(count):
            price = base + prior * step
            total += price * (80 if smith else 100) // 100
    return total


def france_coats(local_rebel, health=0, astor=False, tier=2):
    """3 experts; sufficient fur; ordinary coats, no other modifiers."""
    flat = (2 if tier == 2 else 3) if astor else 0
    multiplier = 100 + 15 + (50 if tier == 3 else 0) + local_rebel // 2 + health
    return (36 + flat) * multiplier // 100


def verify_manifest(path, game_root=None):
    data = json.loads(Path(path).read_text(encoding='utf-8'))
    checked, mismatched, missing = 0, [], []
    for item in data['files']:
        file = Path(game_root) / item['relative_path'] if game_root and item.get('relative_path') else Path(item['relative_path'])
        if not file.is_file():
            missing.append(str(file))
            continue
        digest = hashlib.sha256(file.read_bytes()).hexdigest()
        checked += 1
        if digest.lower() != item['sha256'].lower():
            mismatched.append(str(file))
    return {'checked': checked, 'mismatched': mismatched, 'missing': missing,
            'all_match': not mismatched and not missing}


def self_checks():
    fixed = rebel_latency(40, [80])
    assert fixed == {'turns': None, 'sentiments': [1991], 'reached': False}
    assert rebel_latency(40, [81])['turns'] == 44
    assert rebel_latency(40, [160])['turns'] == 7
    for b in range(1, 30):
        result = rebel_latency(100000, [b], target=100)
        assert result['sentiments'][0] == 25 * b - 9
    equal = combat_odds(Fraction(1, 2), 5, 5)
    assert equal == (Fraction(29, 128), Fraction(29, 128), Fraction(70, 128))
    assert sum(equal) == 1
    assert combat_odds(Fraction(1, 2), 8, 8) == (0, 0, 1)
    for p in [Fraction(1, 10), Fraction(1, 3), Fraction(3, 5), Fraction(9, 10)]:
        a = combat_odds(p, 4, 6)
        b = combat_odds(1 - p, 6, 4)
        assert a[0] == b[1] and a[1] == b[0] and a[2] == b[2]
        assert sum(a) == 1 and all(0 <= x <= 1 for x in a)
    assert combat_from_strengths(10, 10)['draw'] == '35/64'
    assert calendar(215) == {'year': 1669, 'month': 7}
    assert calendar(216) == {'year': 1670, 'month': 1}
    assert calendar(217) == {'year': 1670, 'month': 7}
    assert father_modifier() == 228
    assert [army_cost(8, 4, 3), army_cost(10, 6, 4)] == [42380, 59150]
    assert [army_cost(8, 4, 3, True), army_cost(10, 6, 4, True)] == [33904, 47320]
    assert trunc_div(-19, 10) == -1
    thresholds = []
    for astor, health, expected in [(False, 0, 48), (False, 10, 28),
                                    (True, 0, 34), (True, 10, 14)]:
        minimum = next(r for r in range(101) if france_coats(r, health, astor) >= 50)
        assert minimum == expected
        thresholds.append({'astor': astor, 'health': health, 'local_rebel_min': minimum,
                           'coats': france_coats(minimum, health, astor), 'fur_input': 36})
    assert france_coats(0, tier=3) == 59
    return {
        'self_checks': 'passed',
        'scope': 'Fixed-input models of supplied SDK/XML; not proof of DLL equivalence or a record victory',
        'rebel_P40': {str(b): rebel_latency(40, [b]) for b in [80, 81, 100, 120, 160, 200]},
        'equal_strength_combat': combat_from_strengths(10, 10),
        'exact_equal_strength_fractions': {'kill': '29/128', 'death': '29/128', 'draw': '70/128'},
        'father_modifier': father_modifier(),
        'calendar': {str(t): calendar(t) for t in [164, 178, 196, 197, 215, 216, 217]},
        'army': {'8_4_3': army_cost(8, 4, 3), '10_6_4': army_cost(10, 6, 4),
                 '8_4_3_smith': army_cost(8, 4, 3, True), '10_6_4_smith': army_cost(10, 6, 4, True)},
        'france_T2_coats_thresholds': thresholds,
        'france_T3_coats_no_other_bonuses': france_coats(0, tier=3),
        'cpp_signed_division': {'minus19_div10': trunc_div(-19, 10)},
    }


if __name__ == '__main__':
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-sources', action='store_true')
    parser.add_argument('--game-root', type=Path)
    args = parser.parse_args()
    output = self_checks()
    if args.verify_sources:
        output['source_verification'] = verify_manifest(Path(__file__).parent / 'source_manifest.json', args.game_root)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    if args.verify_sources and not output['source_verification']['all_match']:
        raise SystemExit(1)
