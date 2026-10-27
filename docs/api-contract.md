# О!План contract

All JSON UTF-8. Currency integer RUB, prices for everyone for the entire trip. Dates ISO 8601. Demo inventory version `sochi-demo-v1`.

## Domain (`app/models.py`, parent owned)
`TripRequirements` Pydantic: destination: str|None, origin: str="Москва", check_in: date|None, nights: int=7, adults: int=2, children_ages: list[int]=[], budget: int|None, transport: Literal["flight","train","self"]="flight", direct_only: bool=False, breakfast: bool=False, refundable: bool=False, pets: bool=False, pool: bool=False, quiet: bool=False, accessible: bool=False, max_beach_m: int|None=None, min_rating: float=0, stars: int=0. Hard conditions all booleans except quiet (soft preference). `assumptions: list[str]`, `unsupported: list[str]`, `budget_scope: Literal["trip","hotel"]="trip"`.

`Hotel` and `Plan` are JSON dictionaries. Required Plan fields:
id (stable hash), hotel: {id,name,area,stars,rating,beach_m,description,image (local /static/... optional),amenities:list[str]}, room: {name,rooms:int,capacity:int}, meal: str, refundable: bool, transport: {mode,title,departure,arrival,return_departure,duration_minutes,direct:bool}, transfer: {title,minutes,price}, dates: {check_in,check_out,nights}, guests: {adults,children_ages}, price: {hotel,transport,transfer,extras,total,currency:"RUB"}, reasons:list[str], compromises:list[str], warnings:list[str], score:float, policy: str, timeline:list[{time,title,detail}], data_label:str.

`search(requirements: TripRequirements, limit: int=3) -> dict`: {plans:list[dict], total_matches:int, rejected:dict[str,int], suggestions:list[{field,value,label}], counterfactuals:list[{field,label,saving,baseline_total,alternative_total,alternative_plan_id,note}], catalog_version:str}. Never mutate requirements. `validate_plan(plan:dict, requirements:TripRequirements) -> list[str]` returns blocking errors. `find_plan(requirements, plan_id) -> dict|None` searches all matching candidates. Search/counterfactual agent owns app/catalog.py, app/search.py, tests/test_search.py, static/media only if needed.

## API
`GET /api/config`: {name,parser_mode:"rules"|"llm",catalog_label,destinations:list[{id,name,description,weather,travel}],examples:list[str]}.

`POST /api/sessions` body `{message:string}` creates and processes. `POST /api/sessions/{id}/messages` body `{message:string,revision:int}` updates. `GET /api/sessions/{id}` restores. Session IDs are unguessable capabilities saved to localStorage.

Response Session: {id,revision:int,stage:"clarify"|"results"|"selected"|"booked",requirements:TripRequirements,messages:list[{role:"user"|"assistant",content:string}],assistant_message:string,clarifications:list[{field,question,options:list[{label,value}]}],plans:list[Plan],plan_labels:dict[plan_id,str],total_matches:int,counterfactuals:list[...],suggestions:list[...],selected_plan:Plan|null,order:dict|null,changes:list[{field,label,before,after}],parser_mode:string,data_label:string,assumptions:list[str]}.

`POST /api/sessions/{id}/select` body `{plan_id:string,revision:int}` → Session.
`POST /api/sessions/{id}/checkout` body `{revision:int,accept_demo:true,traveler_name:string,email:string}` → Session. Name 2..100 chars and plausible email required. Order: {id,reference,status:"demo_confirmed",created_at,total,currency,traveler_name,email,plan:Plan,notice:string}. Checkout revalidates and is idempotent. No real card input.

`PATCH /api/sessions/{id}/requirements` body `{revision:int,patch:dict}` for explicit chips/clarification controls → Session. Only allowed TripRequirements fields. Patch changes exactly specified fields, preserves others. Date shift suggestions should send natural language or explicit date.

Errors JSON `{detail:string}` with 404 missing session/plan, 409 stale revision, 422 invalid input. Frontend must show recovery, not fake success. Use textContent or safe escaping; no untrusted innerHTML.

## UX
Brand О!План, a calm contemporary travel product; all visible copy Russian. One clear opening free-text action; no dashboard or filter wall. At most 3 distinct hotel plan options, coherent total prices, concise reasons and honest compromises. Conversation with visible retained conditions, selected trip details, explicit demo checkout, downloadable order through browser-generated JSON. Respect keyboard and reduced motion. External calls must not be required to render the app. No placeholder actions.
