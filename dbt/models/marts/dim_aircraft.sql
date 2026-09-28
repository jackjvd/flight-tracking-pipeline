-- One row per aircraft ever seen.

with positions as (
    select * from {{ ref('stg_flight_states') }}
),

latest as (
    select distinct on (icao24)
        icao24,
        origin_country,
        aircraft_category
    from positions
    order by icao24, snapshot_at desc
),

latest_callsign as (
    select distinct on (icao24)
        icao24,
        callsign
    from positions
    where callsign is not null
    order by icao24, snapshot_at desc
),

stats as (
    select
        icao24,
        min(snapshot_at) as first_seen_at,
        max(snapshot_at) as last_seen_at,
        count(*) as observations
    from positions
    group by icao24
),

flight_counts as (
    select icao24, count(*) as flights
    from {{ ref('fct_flights') }}
    group by icao24
)

select
    stats.icao24,
    latest.origin_country,
    latest_callsign.callsign as latest_callsign,
    latest.aircraft_category,
    stats.first_seen_at,
    stats.last_seen_at,
    stats.observations,
    coalesce(flight_counts.flights, 0) as flights
from stats
join latest using (icao24)
left join latest_callsign using (icao24)
left join flight_counts using (icao24)
