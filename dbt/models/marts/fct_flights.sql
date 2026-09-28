-- One row per flight. OpenSky has no flight IDs, so flights are inferred:
-- a new flight starts when an aircraft first appears, when it hasn't been seen
-- for more than `flight_gap_minutes`, or when its callsign changes.

{% set gap = "interval '" ~ var('flight_gap_minutes') ~ " minutes'" %}

with positions as (
    select * from {{ ref('stg_flight_states') }}
),

with_previous as (
    select
        *,
        lag(snapshot_at) over (partition by icao24 order by snapshot_at) as prev_snapshot_at,
        lag(callsign) over (partition by icao24 order by snapshot_at) as prev_callsign
    from positions
),

flagged as (
    select
        *,
        case
            when prev_snapshot_at is null then 1
            when snapshot_at - prev_snapshot_at > {{ gap }} then 1
            -- A missing callsign is common and doesn't mean a new flight.
            when callsign is not null and prev_callsign is not null and callsign <> prev_callsign then 1
            else 0
        end as is_new_flight
    from with_previous
),

numbered as (
    select
        *,
        sum(is_new_flight) over (
            partition by icao24 order by snapshot_at rows unbounded preceding
        ) as flight_seq
    from flagged
),

flights as (
    select
        icao24,
        flight_seq,
        max(callsign) as callsign,
        max(origin_country) as origin_country,
        min(snapshot_at) as first_seen_at,
        max(snapshot_at) as last_seen_at,
        count(*) as observations,
        max(baro_altitude_m) as max_altitude_m,
        max(velocity_mps) as max_velocity_mps,
        avg(velocity_mps) filter (where not on_ground) as avg_airborne_velocity_mps,
        bool_or(on_ground) as seen_on_ground,
        (array_agg(latitude order by snapshot_at) filter (where latitude is not null))[1] as first_latitude,
        (array_agg(longitude order by snapshot_at) filter (where longitude is not null))[1] as first_longitude,
        (array_agg(latitude order by snapshot_at desc) filter (where latitude is not null))[1] as last_latitude,
        (array_agg(longitude order by snapshot_at desc) filter (where longitude is not null))[1] as last_longitude
    from numbered
    group by icao24, flight_seq
)

select
    md5(icao24 || '-' || first_seen_at::text) as flight_id,
    icao24,
    callsign,
    origin_country,
    first_seen_at,
    last_seen_at,
    extract(epoch from last_seen_at - first_seen_at)::integer as duration_seconds,
    observations,
    max_altitude_m,
    max_velocity_mps,
    avg_airborne_velocity_mps,
    seen_on_ground,
    first_latitude,
    first_longitude,
    last_latitude,
    last_longitude,
    -- Still being tracked: seen within the gap window of the latest snapshot.
    last_seen_at >= (select max(snapshot_at) from positions) - {{ gap }} as is_ongoing
from flights
