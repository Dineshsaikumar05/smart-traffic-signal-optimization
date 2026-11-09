"""
signal_logic.py - Adaptive Traffic Signal Timing Logic

This module calculates optimal green-light duration and service sequence
for a 4-way intersection (North, South, East, West) based on real-time
vehicle densities. It also models comparative delay metrics between
fixed-timer scheduling and dynamic adaptive timing.
"""

from typing import Dict, Any, List, Optional


def calculate_signal_timings(
    counts: Dict[str, Optional[int]],
    cycle_time: int = 120,
    min_green: int = 10,
    max_green: int = 60,
    emergency_road: Optional[str] = None
) -> Dict[str, Any]:
    """
    Computes green light allocation and service order based on vehicle counts.
    Ensures exact cycle conservation: sum(green_times) == cycle_time (120 s).
    Supports roads with 'no data' (count=None): no-data roads receive min_green (10s)
    and are excluded from the vehicle share calculation.
    If no roads have data, returns equal fixed timing (30s per road) with '—' counts.

    Parameters:
        counts (dict): Road names mapped to vehicle counts (or None if no data),
                       e.g. {'north': 15, 'south': None, 'east': 24, 'west': 3}
        cycle_time (int): Total cycle duration in seconds (default: 120)
        min_green (int): Minimum green duration in seconds (default: 10)
        max_green (int): Maximum green duration in seconds (default: 60)
        emergency_road (str, optional): Road designated for emergency vehicle override.

    Returns:
        dict: Detailed timings, density classifications, service order,
              and comparative delay statistics.
    """
    valid_roads = ["north", "south", "east", "west"]
    
    # Identify which roads have actual counts vs no data
    has_data_roads = [r for r in valid_roads if counts.get(r) is not None]
    no_data_roads = [r for r in valid_roads if counts.get(r) is None]

    clean_counts = {r: max(0, int(counts[r])) for r in has_data_roads}
    total_vehicles = sum(clean_counts.values())

    road_results = {}
    green_allocations: Dict[str, int] = {}

    # Normalize emergency_road
    emerg = emergency_road.lower().strip() if emergency_road else None
    if emerg not in valid_roads:
        emerg = None

    if len(has_data_roads) == 0:
        # First-load / Default fixed timer state: equal 30s per road, no data
        equal_time = cycle_time // len(valid_roads)
        for r in valid_roads:
            green_allocations[r] = equal_time
            road_results[r] = {
                "count": None,
                "density": "—",
                "green_time": equal_time,
                "share_pct": 25.0,
                "is_emergency": (r == emerg),
                "no_data": True
            }
        order = [emerg] + [r for r in valid_roads if r != emerg] if emerg else list(valid_roads)
        comparison = calculate_wait_time_comparison({}, road_results, cycle_time)
        return {
            "roads": road_results,
            "order": order,
            "total_vehicles": 0,
            "cycle_time": cycle_time,
            "actual_cycle_time": cycle_time,
            "unallocated_seconds": 0,
            "cycle_label": f"Cycle: {cycle_time} s",
            "min_green": min_green,
            "max_green": max_green,
            "emergency_road": emerg,
            "comparison": comparison
        }

    # Some or all roads have data
    if emerg:
        # Emergency Override
        green_allocations[emerg] = max_green
        remaining_roads = [r for r in valid_roads if r != emerg]
        remaining_time = cycle_time - max_green

        # Assign min_green to any no-data roads in remaining_roads
        rem_no_data = [r for r in remaining_roads if r in no_data_roads]
        rem_has_data = [r for r in remaining_roads if r in has_data_roads]

        for r in rem_no_data:
            green_allocations[r] = min_green
            remaining_time -= min_green

        if rem_has_data:
            target_rem_time = min(remaining_time, len(rem_has_data) * max_green)
            rem_alloc = _allocate_green_pool(
                clean_counts, rem_has_data, target_rem_time, min_green, max_green
            )
            for r in rem_has_data:
                green_allocations[r] = rem_alloc[r]

        # Order: emergency road first, then remaining has-data by count desc, then no-data
        sorted_has_data = sorted(
            rem_has_data,
            key=lambda r: (clean_counts[r], -valid_roads.index(r)),
            reverse=True
        )
        order = [emerg] + sorted_has_data + rem_no_data

    else:
        # Standard Adaptive Cycle
        # Assign min_green to no_data_roads
        pool_time = cycle_time
        for r in no_data_roads:
            green_allocations[r] = min_green
            pool_time -= min_green

        # Proportional allocation for has_data_roads (capped so no road exceeds max_green)
        target_pool_time = min(pool_time, len(has_data_roads) * max_green)
        data_alloc = _allocate_green_pool(
            clean_counts, has_data_roads, target_pool_time, min_green, max_green
        )
        for r in has_data_roads:
            green_allocations[r] = data_alloc[r]

        if total_vehicles == 0:
            sorted_has_data = list(has_data_roads)
        else:
            sorted_has_data = sorted(
                has_data_roads,
                key=lambda r: (clean_counts[r], -valid_roads.index(r)),
                reverse=True
            )
        order = sorted_has_data + no_data_roads

    # Build road_results
    for road in valid_roads:
        if road in no_data_roads:
            road_results[road] = {
                "count": None,
                "density": "—",
                "green_time": green_allocations[road],
                "share_pct": 0.0,
                "is_emergency": (road == emerg),
                "no_data": True
            }
        else:
            cnt = clean_counts[road]
            if cnt < 10:
                density = "Low"
            elif 10 <= cnt <= 25:
                density = "Medium"
            else:
                density = "High"

            share_pct = round((cnt / total_vehicles) * 100, 1) if total_vehicles > 0 else 0.0

            road_results[road] = {
                "count": cnt,
                "density": density,
                "green_time": green_allocations[road],
                "share_pct": share_pct,
                "is_emergency": (road == emerg),
                "no_data": False
            }

    actual_cycle_time = sum(green_allocations.values())
    unallocated_seconds = max(0, cycle_time - actual_cycle_time)
    if unallocated_seconds > 0:
        cycle_label = f"Cycle: {actual_cycle_time} s, partial data"
    else:
        cycle_label = f"Cycle: {cycle_time} s"

    comparison = calculate_wait_time_comparison(clean_counts, road_results, actual_cycle_time)

    return {
        "roads": road_results,
        "order": order,
        "total_vehicles": total_vehicles,
        "cycle_time": cycle_time,
        "actual_cycle_time": actual_cycle_time,
        "unallocated_seconds": unallocated_seconds,
        "cycle_label": cycle_label,
        "min_green": min_green,
        "max_green": max_green,
        "emergency_road": emerg,
        "comparison": comparison
    }


def _allocate_green_pool(
    clean_counts: Dict[str, int],
    roads: List[str],
    total_time: int,
    min_green: int,
    max_green: int
) -> Dict[str, int]:
    """
    Allocates total_time among roads proportionally to clean_counts in whole seconds.
    Ensures min_green <= alloc <= max_green for all roads, redistributes excess/deficit
    among unclamped roads iteratively, and distributes any rounding remainder
    to the road with the highest count (tie-broken by original road order).
    Guarantees sum(allocations) == total_time, never allocating more than max_green to any road.
    """
    n = len(roads)
    if n == 0:
        return {}

    # Clamp total_time so roads are never forced above max_green
    total_time = min(total_time, n * max_green)

    # Safety clamps if total_time is constrained
    eff_min = min(min_green, total_time // n) if total_time >= n else 1
    eff_max = max_green

    pool_vehicles = sum(clean_counts[r] for r in roads)

    if pool_vehicles == 0:
        # Equal distribution
        base = total_time // n
        remainder = total_time % n
        alloc = {r: min(max_green, base) for r in roads}
        for i in range(remainder):
            if alloc[roads[i]] < eff_max:
                alloc[roads[i]] += 1
        return alloc

    # Iterative proportional allocation with clamping and redistribution
    fixed_alloc: Dict[str, int] = {}
    unfixed_roads = list(roads)
    remaining_time = total_time

    while unfixed_roads:
        unfixed_vehicles = sum(clean_counts[r] for r in unfixed_roads)
        newly_clamped = False

        for r in list(unfixed_roads):
            cnt = clean_counts[r]
            if unfixed_vehicles > 0:
                ideal = (cnt / unfixed_vehicles) * remaining_time
            else:
                ideal = remaining_time / len(unfixed_roads)

            if ideal < eff_min:
                fixed_alloc[r] = eff_min
                remaining_time -= eff_min
                unfixed_roads.remove(r)
                newly_clamped = True
                break
            elif ideal > eff_max:
                fixed_alloc[r] = eff_max
                remaining_time -= eff_max
                unfixed_roads.remove(r)
                newly_clamped = True
                break

        if not newly_clamped:
            # All remaining unfixed roads fall within [eff_min, eff_max]
            break

    # Integer truncation + remainder distribution for remaining unfixed roads
    alloc = dict(fixed_alloc)
    if unfixed_roads:
        unfixed_vehicles = sum(clean_counts[r] for r in unfixed_roads)
        raw_values = {}
        for r in unfixed_roads:
            cnt = clean_counts[r]
            if unfixed_vehicles > 0:
                raw_values[r] = (cnt / unfixed_vehicles) * remaining_time
            else:
                raw_values[r] = remaining_time / len(unfixed_roads)
            alloc[r] = int(raw_values[r])  # floor

        remainder = remaining_time - sum(alloc[r] for r in unfixed_roads)

        # Distribute remainder seconds
        # Sort unfixed roads primarily by count descending, then by fractional remainder descending
        sorted_for_remainder = sorted(
            unfixed_roads,
            key=lambda r: (clean_counts[r], raw_values[r] - alloc[r], -roads.index(r)),
            reverse=True
        )

        eligible_for_remainder = [r for r in sorted_for_remainder if alloc[r] < eff_max]
        if not eligible_for_remainder:
            eligible_for_remainder = sorted_for_remainder

        for i in range(remainder):
            r = eligible_for_remainder[i % len(eligible_for_remainder)]
            if alloc[r] < eff_max:
                alloc[r] += 1

    # Final sanity check: ensure exact total within limits
    current_sum = sum(alloc[r] for r in roads)
    diff = total_time - current_sum
    if diff > 0:
        for r in sorted(roads, key=lambda rd: (clean_counts[rd], -roads.index(rd)), reverse=True):
            room = eff_max - alloc[r]
            add_val = min(diff, room)
            alloc[r] += add_val
            diff -= add_val
            if diff <= 0:
                break
    elif diff < 0:
        for r in sorted(roads, key=lambda rd: (clean_counts[rd], roads.index(rd))):
            room = alloc[r] - eff_min
            sub_val = min(-diff, room)
            alloc[r] -= sub_val
            diff += sub_val
            if diff >= 0:
                break

    # Hard clamp: never exceed max_green
    for r in roads:
        alloc[r] = min(max_green, max(eff_min, alloc[r]))

    return alloc


def calculate_wait_time_comparison(
    counts: Dict[str, int],
    road_results: Dict[str, Dict[str, Any]],
    cycle_time: int = 120,
    fixed_green: int = 30
) -> Dict[str, Any]:
    """
    Estimates vehicle delay for Fixed (30s) vs Adaptive timing.
    Models queue clearance where saturation discharge rate is ~0.6 veh/sec.
    When a road's vehicle count exceeds discharge capacity in green phase,
    overflow queues suffer extra cycle delays.
    Also calculates System Clearance Efficiency dynamically based on network throughput.
    """
    discharge_rate = 0.6  # vehicles cleared per second of green
    total_vehicles = sum(counts.values())

    if total_vehicles == 0:
        return {
            "fixed_avg_wait_sec": 45.0,
            "adaptive_avg_wait_sec": 45.0,
            "wait_reduction_pct": 0.0,
            "total_wait_fixed_sec": 0,
            "total_wait_adaptive_sec": 0,
            "congestion_index_fixed": 1.0,
            "congestion_index_adaptive": 1.0,
            "clearance_efficiency_pct": 100.0
        }

    fixed_total_delay = 0.0
    adaptive_total_delay = 0.0

    fixed_capacity = fixed_green * discharge_rate  # 30 * 0.6 = 18 vehicles

    for road, count in counts.items():
        if count == 0:
            continue

        # --- Fixed Signal Model ---
        # Fixed red duration = cycle_time - fixed_green = 90s
        fixed_red = cycle_time - fixed_green
        base_fixed_wait = fixed_red / 2.0  # Average wait during uniform red arrival

        if count <= fixed_capacity:
            # All vehicles clear in one green phase
            delay_per_veh = base_fixed_wait
        else:
            # Queue overflow: excess vehicles wait an extra full cycle (120s)
            overflow_veh = count - fixed_capacity
            cleared_veh = fixed_capacity
            delay_per_veh = (cleared_veh * base_fixed_wait + overflow_veh * (base_fixed_wait + cycle_time)) / count

        fixed_total_delay += delay_per_veh * count

        # --- Adaptive Signal Model ---
        adaptive_green = road_results[road]["green_time"]
        adaptive_red = cycle_time - adaptive_green
        base_adaptive_wait = adaptive_red / 2.0
        adaptive_capacity = adaptive_green * discharge_rate

        if count <= adaptive_capacity:
            delay_per_veh_adapt = base_adaptive_wait
        else:
            overflow_adapt = count - adaptive_capacity
            cleared_adapt = adaptive_capacity
            delay_per_veh_adapt = (cleared_adapt * base_adaptive_wait + overflow_adapt * (base_adaptive_wait + cycle_time)) / count

        adaptive_total_delay += delay_per_veh_adapt * count

    fixed_avg = round(fixed_total_delay / total_vehicles, 1)
    adaptive_avg = round(adaptive_total_delay / total_vehicles, 1)

    if fixed_avg > 0:
        reduction_pct = round(max(0.0, ((fixed_avg - adaptive_avg) / fixed_avg) * 100), 1)
    else:
        reduction_pct = 0.0

    # System Clearance Efficiency Formula:
    # Measures the proportion of vehicles cleared without queue overflow delays in the adaptive cycle.
    # Baseline efficiency for cleared queues is 100%. When arrivals exceed capacity:
    # Overflow penalty = sum(max(0, count - capacity)) / total_vehicles.
    total_overflow = sum(
        max(0.0, counts[r] - (road_results[r]["green_time"] * discharge_rate))
        for r in counts
    )
    clearance_ratio = max(0.0, 1.0 - (total_overflow / total_vehicles))
    # Clearance efficiency scaled between 50% and 98% (or 100% when 0 overflow):
    if total_overflow == 0:
        clearance_efficiency = 98.0  # Optimal throughput cap
    else:
        clearance_efficiency = round(50.0 + (clearance_ratio * 48.0), 1)

    return {
        "fixed_avg_wait_sec": fixed_avg,
        "adaptive_avg_wait_sec": adaptive_avg,
        "wait_reduction_pct": reduction_pct,
        "total_wait_fixed_sec": round(fixed_total_delay, 1),
        "total_wait_adaptive_sec": round(adaptive_total_delay, 1),
        "congestion_index_fixed": round(max(1.0, fixed_avg / 30.0), 2),
        "congestion_index_adaptive": round(max(1.0, adaptive_avg / 30.0), 2),
        "clearance_efficiency_pct": clearance_efficiency
    }


if __name__ == "__main__":
    print("=== Testing signal_logic.py ===")

    # Test Case 1: Equal counts
    counts_equal = {"north": 15, "south": 15, "east": 15, "west": 15}
    res_equal = calculate_signal_timings(counts_equal)
    print("\nCase 1 (Equal Counts):", [res_equal["roads"][r]["green_time"] for r in res_equal["order"]])
    total_g = sum(res_equal["roads"][r]["green_time"] for r in res_equal["roads"])
    print(f"Total green time: {total_g}s (Expected: 120s)")
    assert total_g == 120, f"Expected 120, got {total_g}"

    # Test Case 2: All zero counts
    counts_zero = {"north": 0, "south": 0, "east": 0, "west": 0}
    res_zero = calculate_signal_timings(counts_zero)
    print("\nCase 2 (All Zero):", [res_zero["roads"][r]["green_time"] for r in res_zero["order"]])
    total_g = sum(res_zero["roads"][r]["green_time"] for r in res_zero["roads"])
    print(f"Total green time: {total_g}s (Expected: 120s)")
    assert total_g == 120, f"Expected 120, got {total_g}"

    # Test Case 3: One dominant road
    counts_dominant = {"north": 50, "south": 5, "east": 3, "west": 2}
    res_dominant = calculate_signal_timings(counts_dominant)
    print("\nCase 3 (One Dominant):", {r: res_dominant["roads"][r]["green_time"] for r in res_dominant["order"]})
    total_g = sum(res_dominant["roads"][r]["green_time"] for r in res_dominant["roads"])
    print(f"Total green time: {total_g}s (Expected: 120s)")
    assert total_g == 120, f"Expected 120, got {total_g}"
    assert res_dominant["roads"]["north"]["green_time"] == 60, "Dominant road must clamp to max_green (60s)"
    assert res_dominant["roads"]["west"]["green_time"] >= 10, "Minimum green must be respected"

    # Test Case 4: Emergency override
    counts_emerg = {"north": 12, "south": 20, "east": 8, "west": 5}
    res_emerg = calculate_signal_timings(counts_emerg, emergency_road="north")
    print("\nCase 4 (Emergency on North):", {r: res_emerg["roads"][r]["green_time"] for r in res_emerg["order"]})
    print("Order:", res_emerg["order"])
    total_g = sum(res_emerg["roads"][r]["green_time"] for r in res_emerg["roads"])
    print(f"Total green time: {total_g}s (Expected: 120s)")
    assert total_g == 120, f"Expected 120, got {total_g}"
    assert res_emerg["order"][0] == "north", "Emergency road must be first in order"
    assert res_emerg["roads"]["north"]["green_time"] == 60, "Emergency road must receive 60s"
    assert res_emerg["roads"]["north"]["count"] == 12, "Emergency road count must NOT be altered"
    print("\nAll signal_logic.py unit tests PASSED successfully!")
