"""Which job an uploaded estimate belongs to: automatic when sure, a person decides when not.

match_job() answers one of
  Match("job", job)                      - file it with that job
  Match("new")                           - nothing matches: a new job
  Match("person", reason, candidates)    - a person chooses (the upload waits in pending_uploads)
Rules, in order (docs/data-model.md):
  1. Same RO # -> that job, unless both print a VIN and the VINs differ (person).
  2. Same claim # -> that job only if both print the same VIN. Both VINs printed and different -> not this job (one
     accident can bring two cars under one claim #): keep looking. Either VIN missing -> person.
  3. Same VIN with an estimate printed within VIN_MATCH_DAYS and no conflicting claim # -> that job.
  4. More than one candidate job at any step -> person.
  5. No match -> new job.
  6. The matched job is closed -> person (it is locked until someone reopens it)."""
from dataclasses import dataclass, field

from sqlalchemy import select

from .models import Job, Vehicle
from .values import printed_time

VIN_MATCH_DAYS = 90

UNCERTAIN = "uncertain_match"
CLOSED = "closed_job"
DUPLICATE_RO = "duplicate_ro"
REASONS = {UNCERTAIN: "Not sure which job this estimate belongs to",
           CLOSED: "The job this estimate belongs to is closed",
           DUPLICATE_RO: "Another job already has this RO #"}


@dataclass
class Match:
    kind: str  # job | new | person
    job: Job | None = None
    reason: str = ""  # for 'person': one of REASONS
    detail: str = ""  # one sentence a person reads
    candidates: list = field(default_factory=list)


def _vin(job):
    return job.vehicle.vin if job.vehicle else ""


def _person(candidates, detail, reason=UNCERTAIN):
    return Match("person", reason=reason, detail=detail, candidates=list(candidates))


def _found(job, why):
    if job.closed_at is not None:
        return _person([job], f"{why}, and that job is closed. Reopen it to add this estimate, or make a new job.", CLOSED)
    return Match("job", job, detail=why)


def match_job(s, shop_id, ro="", claim="", vin="", printed=""):
    """ro, claim, vin: as the estimate prints them; printed: its print time (ISO text, shop time)."""
    jobs = select(Job).where(Job.shop_id == shop_id).order_by(Job.id)

    if ro:
        found = s.scalars(jobs.where(Job.ro_number == ro)).all()
        if len(found) > 1:
            return _person(found, f"{len(found)} jobs have RO # {ro}.")
        if found:
            job = found[0]
            if vin and _vin(job) and vin != _vin(job):
                return _person([job], f"Same RO # {ro}, but the VINs differ ({vin} here, {_vin(job)} on the job).")
            return _found(job, f"Same RO # {ro}")

    if claim:
        found = [j for j in s.scalars(jobs.where(Job.claim_no == claim))
                 if not (vin and _vin(j) and vin != _vin(j))]  # another car on the same claim is another job
        if len(found) > 1:
            return _person(found, f"{len(found)} jobs have claim # {claim}.")
        if found:
            job = found[0]
            if vin and _vin(job) == vin:
                return _found(job, f"Same claim # {claim} and VIN")
            return _person([job], f"Same claim # {claim}, but {'this estimate' if not vin else 'the job'} has no VIN "
                                  "to confirm it is the same car.")

    if vin and printed:
        when = printed_time(printed)
        found = []
        for job in s.scalars(jobs.where(Job.vehicle.has(Vehicle.vin == vin))):
            cur = job.current_document
            if claim and job.claim_no and claim != job.claim_no:
                continue  # same car, different claim: a different job
            if cur and cur.printed_at and abs((cur.printed_at - when).days) <= VIN_MATCH_DAYS:
                found.append(job)
        if len(found) > 1:
            return _person(found, f"{len(found)} jobs have VIN {vin} with an estimate within {VIN_MATCH_DAYS} days.")
        if found:
            return _found(found[0], f"Same VIN, estimate within {VIN_MATCH_DAYS} days")

    return Match("new")
