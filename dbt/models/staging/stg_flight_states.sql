-- Cleaned aircraft positions: one row per aircraft per snapshot.

with source as (
    select * from {{ source('raw', 'flight_states') }}
),

deduped as (
    -- An aircraft can appear twice in one snapshot; keep the most recently loaded row.
    select distinct on (icao24, snapshot_time) *
    from source
    order by icao24, snapshot_time, loaded_at desc, last_contact desc
)

select
    md5(icao24 || '-' || snapshot_time::text) as state_id,
    icao24,
    nullif(trim(callsign), '') as callsign,
    origin_country,
    to_timestamp(snapshot_time) as snapshot_at,
    to_timestamp(time_position) as position_at,
    to_timestamp(last_contact) as last_contact_at,
    longitude,
    latitude,
    baro_altitude as baro_altitude_m,
    geo_altitude as geo_altitude_m,
    on_ground,
    velocity as velocity_mps,
    true_track as heading_deg,
    vertical_rate as vertical_rate_mps,
    squawk,
    spi,
    case position_source
        when 0 then 'ADS-B'
        when 1 then 'ASTERIX'
        when 2 then 'MLAT'
        when 3 then 'FLARM'
    end as position_source,
    category as aircraft_category,
    source_file,
    loaded_at
from deduped
