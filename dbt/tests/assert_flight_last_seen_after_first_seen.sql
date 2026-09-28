-- A flight can't end before it starts.
select flight_id, first_seen_at, last_seen_at
from {{ ref('fct_flights') }}
where last_seen_at < first_seen_at
