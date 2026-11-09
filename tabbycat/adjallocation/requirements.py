from collections import Counter
from typing import Dict, List, NamedTuple

from participants.models import Adjudicator, Institution, Team
from tournaments.models import Round

from .models import AdjudicatorRequirementAssignment, AdjudicatorRequirementException, DebateAdjudicator

RULE_TYPE_N_MINUS_1 = 'n_minus_1'
RULE_TYPE_N_EQUALS_N = 'n_equals_n'
RULE_TYPE_RATIO = 'ratio'


def required_judges(team_count, rule_type, ratio_divisor) -> int:
    if rule_type == RULE_TYPE_N_MINUS_1:
        return max(0, team_count - 1)
    elif rule_type == RULE_TYPE_N_EQUALS_N:
        return team_count
    elif rule_type == RULE_TYPE_RATIO:
        return team_count // ratio_divisor  # floor, not ceiling
    else:
        raise ValueError("Unknown adjudicator requirement rule_type: %r" % (rule_type,))


class AssignedJudge(NamedTuple):
    adjudicator: Adjudicator
    rounds_judged: int
    qualifies: bool


class InstitutionRequirementStatus(NamedTuple):
    institution: Institution
    team_count: int
    required: int
    coverage: int
    required_coverage: int
    exceptions_granted: int
    compliant: bool
    partial: bool
    judges: List[AssignedJudge]


class TeamRequirementStatus(NamedTuple):
    team: Team
    required: int
    coverage: int
    required_coverage: int
    exceptions_granted: int
    compliant: bool
    partial: bool
    judges: List[AssignedJudge]


class AdjudicatorRequirementsInfo:

    def __init__(self, tournament, min_rounds, strict, rule_type, ratio_divisor):
        self.tournament = tournament
        self.min_rounds = min_rounds
        self.strict = strict
        self.rule_type = rule_type
        self.ratio_divisor = ratio_divisor
        self._fetch_requirements_from_db()

    def _fetch_requirements_from_db(self):
        self._institutions = list(
            Institution.objects.filter(team__tournament=self.tournament).distinct())
        self._independent_teams = list(
            Team.objects.filter(tournament=self.tournament, institution__isnull=True))

        rj_rows = DebateAdjudicator.objects.filter(
            debate__round__tournament=self.tournament,
            debate__round__stage=Round.Stage.PRELIMINARY,
        ).values('adjudicator_id', 'debate__round_id').distinct()
        self._rounds_judged = Counter(row['adjudicator_id'] for row in rj_rows)

        team_rows = Team.objects.filter(
            tournament=self.tournament, institution__isnull=False,
        ).values('institution_id')
        self._team_counts = Counter(row['institution_id'] for row in team_rows)

        self._assignments_by_institution: Dict[int, list] = {}
        self._assignments_by_team: Dict[int, list] = {}
        assignments = AdjudicatorRequirementAssignment.objects.filter(
            adjudicator__tournament=self.tournament,
        ).select_related('adjudicator')
        for a in assignments:
            if a.institution_id is not None:
                self._assignments_by_institution.setdefault(a.institution_id, []).append(a)
            else:
                self._assignments_by_team.setdefault(a.team_id, []).append(a)

        exceptions = AdjudicatorRequirementException.objects.filter(tournament=self.tournament)
        self._exceptions_by_institution = {
            e.institution_id: e.count for e in exceptions if e.institution_id is not None}
        self._exceptions_by_team = {
            e.team_id: e.count for e in exceptions if e.team_id is not None}

    def rounds_judged(self, adjudicator) -> int:
        return self._rounds_judged[adjudicator.id]

    def _judges_for(self, assignments) -> List[AssignedJudge]:
        return [
            AssignedJudge(
                adjudicator=a.adjudicator,
                rounds_judged=self.rounds_judged(a.adjudicator),
                qualifies=self.rounds_judged(a.adjudicator) >= self.min_rounds,
            )
            for a in assignments
        ]

    def institution_status(self, institution) -> InstitutionRequirementStatus:

        team_count = self._team_counts.get(institution.id, 0)
        required = required_judges(team_count, self.rule_type, self.ratio_divisor)
        assignments = self._assignments_by_institution.get(institution.id, [])
        exceptions_granted = self._exceptions_by_institution.get(institution.id, 0)
        judges = self._judges_for(assignments)

        if self.strict:
            coverage = sum(1 for j in judges if j.qualifies) + exceptions_granted
            required_coverage = required
        else:
            coverage = sum(j.rounds_judged for j in judges) + exceptions_granted * self.min_rounds
            required_coverage = required * self.min_rounds

        compliant = required == 0 or coverage >= required_coverage
        partial = not compliant and exceptions_granted > 0

        return InstitutionRequirementStatus(
            institution=institution, team_count=team_count, required=required,
            coverage=coverage, required_coverage=required_coverage,
            exceptions_granted=exceptions_granted, compliant=compliant,
            partial=partial, judges=judges)

    def team_status(self, team) -> TeamRequirementStatus:

        assignments = self._assignments_by_team.get(team.id, [])
        exceptions_granted = self._exceptions_by_team.get(team.id, 0)
        judges = self._judges_for(assignments)

        coverage = sum(1 for j in judges if j.qualifies) + exceptions_granted
        required_coverage = 1
        compliant = coverage >= required_coverage

        return TeamRequirementStatus(
            team=team, required=1, coverage=coverage,
            required_coverage=required_coverage, exceptions_granted=exceptions_granted,
            compliant=compliant, partial=False, judges=judges)

    def all_institution_statuses(self) -> List[InstitutionRequirementStatus]:
        return [self.institution_status(inst) for inst in self._institutions]

    def all_independent_team_statuses(self) -> List[TeamRequirementStatus]:
        return [self.team_status(team) for team in self._independent_teams]