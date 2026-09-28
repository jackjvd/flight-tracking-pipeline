-- The flight sessionization must account for every staged position exactly once.
select
    (select count(*) from {{ ref('stg_flight_states') }}) as positions,
    (select coalesce(sum(observations), 0) from {{ ref('fct_flights') }}) as flight_observations
where (select count(*) from {{ ref('stg_flight_states') }})
   <> (select coalesce(sum(observations), 0) from {{ ref('fct_flights') }})
