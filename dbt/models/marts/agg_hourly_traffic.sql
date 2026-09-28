-- Traffic per hour and country of registration.

select
    date_trunc('hour', snapshot_at) as hour,
    origin_country,
    count(distinct icao24) as aircraft,
    count(distinct icao24) filter (where not on_ground) as airborne_aircraft,
    count(*) as observations,
    avg(baro_altitude_m) filter (where not on_ground) as avg_airborne_altitude_m,
    avg(velocity_mps) filter (where not on_ground) as avg_airborne_velocity_mps
from {{ ref('stg_flight_states') }}
group by 1, 2
