# O!RIVANE contract

All JSON UTF-8. Currency integer RUB, prices for everyone for the entire trip. Dates ISO 8601. Demo inventory version `sochi-demo-v1`.

## Domain (`app/models.py`)
`TripRequirements` Pydantic: destination: str|None, origin: str="Москва", check_in: date|None, nights: int=7, adults: int=2, children_ages: list[int]=[], budget: int|None, transport: Literal["flight","train","self"]="flight", direct_only: bool=False, breakfast: bool=False, refundable: bool=False, pets: bool=False, pool: bool=False, quiet: bool=False, accessible: bool=False, max_beach_m: int|None=None, min_rating: float=0, stars: int=0. `assumptions: list[str]`, `unsupported: list[str]`, `budget_scope: Literal["trip","hotel"]="trip"`.

`preference_modes: dict[field, "required"|"preferred"]` permits only breakfast, pool, refundable, quiet, direct_only, max_beach_m, min_rating, stars. Missing modes preserve legacy required semantics except quiet (preferred). Inactive values remove conditions, never forbid included amenities. `max_beach_m=0` is an active zero-distance condition; only null clears it. Preferred conditions affect ranking and truthful `Plan.preference_matches` / `preference_compromises`; budget, guests, pets and accessibility remain hard. `search_terms(req)` excludes assumption provenance and redundant/inactive modes from semantic quote IDs.

`Hotel` and `Plan` are JSON dictionaries. Required Plan fields:
id (stable hash), hotel: {id,name,area,stars,rating,beach_m,description,image (local /static/... optional),amenities:list[str]}, room: {name,rooms:int,capacity:int}, meal: str, refundable: bool, transport: {mode,title,departure,arrival,return_departure,duration_minutes,direct:bool}, transfer: {title,minutes,price}, dates: {check_in,check_out,nights}, guests: {adults,children_ages}, price: {hotel,transport,transfer,extras,total,currency:"RUB"}, reasons:list[str], compromises:list[str], warnings:list[str], score:float, policy: str, timeline:list[{time,title,detail}], data_label:str.

`search(requirements, limit=3, *, hotel_id=None) -> dict`: {plans, plan_labels, total_matches, min_total, rejected, diagnostic, suggestions, counterfactuals, catalog_version}. `total_matches` counts distinct hotels; `min_total` is the actual minimum across all eligible tariffs, not just displayed preference-ranked representatives. Suggestions contain `{patch,label,total_matches,min_total}`; singles also retain legacy `field,value`. Each patch is verified by the same search and hotel scope; singles precede bounded pairs, then lower full price. No automatic relaxation or removal of pets/accessibility. Diagnostics distinguish unsupported input/destination, budget, availability, constraints and retained hotel conflicts. `validate_plan(plan, requirements)` returns blocking errors. `find_plan(requirements, plan_id, *, hotel_id=None)` searches all eligible canonical tariffs. Functions never mutate requirements.

## API
`GET /api/config`: {name,parser_mode:"rules"|"llm",catalog_label,destinations:list[{id,name,description,weather,travel}],examples:list[str]}.

`POST /api/sessions` body `{message:string}` creates and processes. `POST /api/sessions/{id}/messages` body `{message:string,revision:int}` updates. `GET /api/sessions/{id}` restores. Session IDs are unguessable capabilities saved to localStorage.

Response Session: {id,revision:int,stage:"clarify"|"results"|"selected"|"booked",requirements:TripRequirements,messages:list[{role:"user"|"assistant",content:string}],assistant_message:string,clarifications:list[{field,question,options:list[{label,value}]}],plans:list[Plan],plan_labels:dict[plan_id,str],total_matches:int,counterfactuals:list[...],suggestions:list[...],selected_plan:Plan|null,order:dict|null,changes:list[{field,label,before,after}],parser_mode:string,data_label:string,assumptions:list[str]}.

Session v2 also exposes `hotel_intent:{id,name}|null`, `hotel_alternative:{total_matches,min_total,label}|null`, `diagnostic`, `hypothetical`, `request_status:"idle"|"needs_clarification"`, and human-readable `changes[].summary`. Private pending questions/metrics are omitted. Child questions may include `expected_count`, `additional_count`, `existing_ages`; incomplete counts do not overwrite confirmed guests. Legacy JSON requirements default safely, unbooked offers refresh and require confirmation, booked orders remain historical records.

| Event | Persistent trip / offer | Request status |
| --- | --- | --- |
| Missing essential details | clarify; no bookable offer | needs_clarification |
| Valid search | results | idle |
| Explicit offer selection | selected; retain hotel intention | idle |
| Meaningful condition change | recheck only retained hotel; results, old offer invalid | idle or needs_clarification |
| Unknown text or semantic no-op | preserve trip and offer | preserve pending clarification |
| Ambiguous change | preserve confirmed state/offer for reference | needs_clarification; checkout blocked |
| What-if and its bounded follow-up answers | search separate branch; preserve live trip/offer | live status unchanged |
| Explicit consider other hotels | release intention, search original conditions | idle |
| Checkout | requires current revision, confirmed canonical offer, no pending question; booked | idle |

Hypothetical result includes `{patch,total_matches,min_total,baseline_min_total,diagnostic,hotel_id}`. It is cleared on actual edits/new selection/checkout. Applying it uses the ordinary revision-checked PATCH, never automatic mutation.

`POST /api/sessions/{id}/select` body `{plan_id:string,revision:int}` → Session.
`POST /api/sessions/{id}/checkout` body `{revision:int,accept_demo:true,traveler_name:string,email:string}` → Session. Name 2..100 chars and plausible email required. Order: {id,reference,status:"demo_confirmed",created_at,total,currency,traveler_name,email,plan:Plan,notice:string}. Checkout revalidates and is idempotent. No real card input.

`PATCH /api/sessions/{id}/requirements` body `{revision:int,patch:dict}` for explicit chips/clarification controls → Session. Only allowed TripRequirements fields. Patch changes exactly specified fields, preserves others; nested preference modes merge per field. Date shift suggestions should send natural language or explicit date.

Errors JSON `{detail:string}` with 404 missing session/plan, 409 stale revision, 422 invalid input. Frontend must show recovery, not fake success. Use textContent or safe escaping; no untrusted innerHTML.

## UX
Brand O!RIVANE, a premium contemporary travel product; all visible copy Russian. One clear opening free-text action; no dashboard or filter wall. At most 3 distinct hotel plan options, coherent total prices, concise reasons and honest compromises. Conversation with visible retained conditions, selected trip details, explicit demo checkout, downloadable order through browser-generated JSON. Respect keyboard and reduced motion. External calls must not be required to render the app. No placeholder actions. Saved-trip navigation stores capability IDs and display metadata locally and restores through the existing GET session endpoint; it does not imply an account or change the API/state schema. Legacy `oplan-session-v1` stays supported to preserve existing sessions.
