from django.test import TestCase

from adjallocation.models import AdjudicatorRequirementAssignment, AdjudicatorRequirementException, DebateAdjudicator
from draw.models import Debate
from participants.models import Adjudicator, Institution, Team
from tournaments.models import Round, Tournament

from ..requirements import AdjudicatorRequirementsInfo, required_judges


class RequiredJudgesTest(TestCase):

    def test_n_minus_1_zero_teams(self):
        self.assertEqual(required_judges(0, 'n_minus_1', 3), 0)

    def test_n_minus_1_one_team(self):
        self.assertEqual(required_judges(1, 'n_minus_1', 3), 0)

    def test_n_minus_1_multiple_teams(self):
        self.assertEqual(required_judges(5, 'n_minus_1', 3), 4)

    def test_n_equals_n_zero_teams(self):
        self.assertEqual(required_judges(0, 'n_equals_n', 3), 0)

    def test_n_equals_n_one_team(self):
        self.assertEqual(required_judges(1, 'n_equals_n', 3), 1)

    def test_n_equals_n_multiple_teams(self):
        self.assertEqual(required_judges(5, 'n_equals_n', 3), 5)

    def test_ratio_zero_teams(self):
        self.assertEqual(required_judges(0, 'ratio', 3), 0)

    def test_ratio_below_divisor(self):
        self.assertEqual(required_judges(2, 'ratio', 3), 0)

    def test_ratio_exact_multiple(self):
        self.assertEqual(required_judges(6, 'ratio', 3), 2)

    def test_ratio_floors_not_ceils(self):
        self.assertEqual(required_judges(7, 'ratio', 3), 2)

    def test_ratio_divisor_one(self):
        self.assertEqual(required_judges(4, 'ratio', 1), 4)

    def test_unknown_rule_type_raises(self):
        self.assertRaises(ValueError, required_judges, 5, 'bogus', 3)


class AdjudicatorRequirementsInfoTest(TestCase):

    def setUp(self):
        self.tournament = Tournament.objects.create(slug='reqs-t1')
        self.other_tournament = Tournament.objects.create(slug='reqs-t2')

        self.alpha = Institution.objects.create(code="Alpha", name="Alpha")
        self.beta = Institution.objects.create(code="Beta", name="Beta")

        for ref, inst in [(0, self.alpha), (1, self.alpha), (2, self.alpha), (3, self.beta)]:
            Team.objects.create(tournament=self.tournament, institution=inst, reference=ref)
        for ref in (4, 5):
            Team.objects.create(tournament=self.tournament, institution=None, reference=ref)

        for seq in range(1, 5):
            Round.objects.create(tournament=self.tournament, seq=seq, schedule_group=seq,
                abbreviation="R%d" % seq, stage=Round.Stage.PRELIMINARY)
        Round.objects.create(tournament=self.tournament, seq=5, schedule_group=5,
            abbreviation="E1", stage=Round.Stage.ELIMINATION)

        for i in range(10):
            Adjudicator.objects.create(tournament=self.tournament, name=i)

    def tearDown(self):
        AdjudicatorRequirementException.objects.all().delete()
        AdjudicatorRequirementAssignment.objects.all().delete()
        DebateAdjudicator.objects.all().delete()
        Debate.objects.all().delete()
        Adjudicator.objects.all().delete()
        Team.objects.all().delete()
        Institution.objects.all().delete()
        self.tournament.delete()
        self.other_tournament.delete()

    def _team(self, ref, tournament=None):
        return Team.objects.get(tournament=tournament or self.tournament, reference=ref)

    def _adj(self, name, tournament=None):
        return Adjudicator.objects.get(tournament=tournament or self.tournament, name=name)

    def _round(self, seq, tournament=None):
        return Round.objects.get(tournament=tournament or self.tournament, seq=seq)

    def _judge(self, adj, round_seq, tournament=None):
        debate = Debate.objects.create(round=self._round(round_seq, tournament))
        DebateAdjudicator.objects.create(debate=debate, adjudicator=adj, type=DebateAdjudicator.TYPE_CHAIR)

    def _judge_twice_same_round(self, adj, round_seq):
        rd = self._round(round_seq)
        DebateAdjudicator.objects.create(debate=Debate.objects.create(round=rd), adjudicator=adj,
            type=DebateAdjudicator.TYPE_CHAIR)
        DebateAdjudicator.objects.create(debate=Debate.objects.create(round=rd), adjudicator=adj,
            type=DebateAdjudicator.TYPE_CHAIR)

    def _assign(self, adj, institution=None, team=None):
        return AdjudicatorRequirementAssignment.objects.create(adjudicator=adj, institution=institution, team=team)

    def _except(self, count, tournament=None, institution=None, team=None):
        return AdjudicatorRequirementException.objects.create(
            tournament=tournament or self.tournament, count=count, institution=institution, team=team)

    def _info(self, min_rounds=2, strict=False, rule_type='n_minus_1', ratio_divisor=3, tournament=None):
        return AdjudicatorRequirementsInfo(tournament or self.tournament, min_rounds=min_rounds,
            strict=strict, rule_type=rule_type, ratio_divisor=ratio_divisor)

    # ==========================================================================
    # Rounds judged
    # ==========================================================================

    def test_rounds_judged_counts_distinct_prelim_rounds(self):
        adj = self._adj(0)
        self._judge(adj, 1)
        self._judge(adj, 2)
        self._judge(adj, 3)
        info = self._info()
        self.assertEqual(info.rounds_judged(adj), 3)

    def test_rounds_judged_same_round_multiple_debates_counts_once(self):
        adj = self._adj(0)
        self._judge_twice_same_round(adj, 1)
        info = self._info()
        self.assertEqual(info.rounds_judged(adj), 1)

    def test_rounds_judged_excludes_elimination_rounds(self):
        adj = self._adj(0)
        self._judge(adj, 1)
        self._judge(adj, 2)
        self._judge(adj, 5)
        info = self._info()
        self.assertEqual(info.rounds_judged(adj), 2)

    def test_rounds_judged_zero_for_unjudged_adjudicator(self):
        adj = self._adj(0)
        info = self._info()
        self.assertEqual(info.rounds_judged(adj), 0)

    def test_rounds_judged_scoped_to_tournament(self):
        Round.objects.create(tournament=self.other_tournament, seq=1, schedule_group=1,
            abbreviation="R1", stage=Round.Stage.PRELIMINARY)
        adj = self._adj(0)
        adj.tournament = self.other_tournament
        adj.save()
        self._judge(adj, 1, tournament=self.other_tournament)
        info = self._info()
        self.assertEqual(info.rounds_judged(adj), 0)

    # ==========================================================================
    # Institution status
    # ==========================================================================

    def test_institution_status_vacuously_compliant_when_required_zero(self):
        info = self._info(rule_type='n_minus_1')
        status = info.institution_status(self.beta)
        self.assertEqual(status.required, 0)
        self.assertTrue(status.compliant)

    def test_institution_status_team_count_scoped_to_tournament(self):
        Team.objects.create(tournament=self.other_tournament, institution=self.alpha, reference=100)
        info = self._info()
        status = info.institution_status(self.alpha)
        self.assertEqual(status.team_count, 3)

    def test_institution_status_strict_ignores_non_qualifying_judges(self):
        adj0, adj1, adj2 = self._adj(0), self._adj(1), self._adj(2)
        self._judge(adj0, 1)
        self._judge(adj0, 2)
        self._judge(adj1, 1)
        self._judge(adj2, 1)
        for adj in (adj0, adj1, adj2):
            self._assign(adj, institution=self.alpha)
        info = self._info(min_rounds=2, strict=True)
        status = info.institution_status(self.alpha)
        self.assertEqual(status.coverage, 1)

    def test_institution_status_strict_boundary_compliant(self):
        adj0, adj1 = self._adj(0), self._adj(1)
        for adj in (adj0, adj1):
            self._judge(adj, 1)
            self._judge(adj, 2)
            self._assign(adj, institution=self.alpha)
        info = self._info(min_rounds=2, strict=True, rule_type='n_minus_1')
        status = info.institution_status(self.alpha)
        self.assertEqual(status.required, 2)
        self.assertEqual(status.coverage, 2)
        self.assertTrue(status.compliant)

    def test_institution_status_strict_boundary_noncompliant(self):
        adj0 = self._adj(0)
        self._judge(adj0, 1)
        self._judge(adj0, 2)
        self._assign(adj0, institution=self.alpha)
        info = self._info(min_rounds=2, strict=True, rule_type='n_minus_1')
        status = info.institution_status(self.alpha)
        self.assertEqual(status.required, 2)
        self.assertEqual(status.coverage, 1)
        self.assertFalse(status.compliant)

    def test_institution_status_non_strict_sums_rounds_judged(self):
        adj0, adj1 = self._adj(0), self._adj(1)
        self._judge(adj0, 1)
        self._judge(adj1, 1)
        self._judge(adj1, 2)
        self._assign(adj0, institution=self.alpha)
        self._assign(adj1, institution=self.alpha)
        info = self._info(min_rounds=2, strict=False)
        status = info.institution_status(self.alpha)
        self.assertEqual(status.coverage, 3)

    def test_institution_status_non_strict_boundary_compliant(self):
        adj0 = self._adj(0)
        self._judge(adj0, 1)
        self._judge(adj0, 2)
        self._judge(adj0, 3)
        self._judge(adj0, 4)
        self._assign(adj0, institution=self.alpha)
        info = self._info(min_rounds=2, strict=False, rule_type='n_minus_1')
        status = info.institution_status(self.alpha)
        self.assertEqual(status.required_coverage, 4)
        self.assertEqual(status.coverage, 4)
        self.assertTrue(status.compliant)

    def test_institution_status_non_strict_boundary_noncompliant(self):
        adj0 = self._adj(0)
        self._judge(adj0, 1)
        self._judge(adj0, 2)
        self._judge(adj0, 3)
        self._assign(adj0, institution=self.alpha)
        info = self._info(min_rounds=2, strict=False, rule_type='n_minus_1')
        status = info.institution_status(self.alpha)
        self.assertEqual(status.required_coverage, 4)
        self.assertEqual(status.coverage, 3)
        self.assertFalse(status.compliant)

    def test_institution_status_exception_strict_contribution(self):
        self._except(1, institution=self.beta)
        info = self._info(min_rounds=2, strict=True, rule_type='n_equals_n')
        status = info.institution_status(self.beta)
        self.assertEqual(status.required, 1)
        self.assertEqual(status.coverage, 1)
        self.assertTrue(status.compliant)

    def test_institution_status_exception_non_strict_contribution(self):
        self._except(1, institution=self.beta)
        info = self._info(min_rounds=3, strict=False, rule_type='n_equals_n')
        status = info.institution_status(self.beta)
        self.assertEqual(status.required_coverage, 3)
        self.assertEqual(status.coverage, 3)
        self.assertTrue(status.compliant)

    def test_institution_status_partial_when_exception_insufficient(self):
        self._except(1, institution=self.alpha)
        info = self._info(min_rounds=2, strict=True, rule_type='n_minus_1')
        status = info.institution_status(self.alpha)
        self.assertEqual(status.required, 2)
        self.assertEqual(status.coverage, 1)
        self.assertFalse(status.compliant)
        self.assertTrue(status.partial)

    def test_institution_status_not_partial_when_compliant(self):
        self._except(2, institution=self.alpha)
        info = self._info(min_rounds=2, strict=True, rule_type='n_minus_1')
        status = info.institution_status(self.alpha)
        self.assertTrue(status.compliant)
        self.assertFalse(status.partial)

    def test_institution_status_not_partial_without_exceptions(self):
        info = self._info(min_rounds=2, strict=True, rule_type='n_minus_1')
        status = info.institution_status(self.alpha)
        self.assertFalse(status.compliant)
        self.assertFalse(status.partial)

    def test_all_institution_statuses_only_institutions_with_teams_in_tournament(self):
        Institution.objects.create(code="Gamma", name="Gamma")
        info = self._info()
        institutions = {status.institution for status in info.all_institution_statuses()}
        self.assertEqual(institutions, {self.alpha, self.beta})

    def test_all_institution_statuses_covers_all_configured_institutions(self):
        info = self._info()
        statuses = info.all_institution_statuses()
        self.assertEqual(len(statuses), 2)

    # ==========================================================================
    # Independent team status
    # ==========================================================================

    def test_team_status_compliant_with_qualifying_judge(self):
        adj = self._adj(0)
        self._judge(adj, 1)
        self._judge(adj, 2)
        self._assign(adj, team=self._team(4))
        info = self._info(min_rounds=2)
        status = info.team_status(self._team(4))
        self.assertTrue(status.compliant)

    def test_team_status_noncompliant_with_non_qualifying_judge(self):
        adj = self._adj(0)
        self._judge(adj, 1)
        self._assign(adj, team=self._team(4))
        info = self._info(min_rounds=2)
        status = info.team_status(self._team(4))
        self.assertFalse(status.compliant)

    def test_team_status_compliant_via_exception_alone(self):
        self._except(1, team=self._team(4))
        info = self._info(min_rounds=2)
        status = info.team_status(self._team(4))
        self.assertTrue(status.compliant)

    def test_team_status_noncompliant_with_nothing(self):
        info = self._info(min_rounds=2)
        status = info.team_status(self._team(4))
        self.assertFalse(status.compliant)

    def test_team_status_partial_always_false(self):
        info = self._info(min_rounds=2)
        self.assertFalse(info.team_status(self._team(4)).partial)
        self._except(1, team=self._team(5))
        info = self._info(min_rounds=2)
        self.assertFalse(info.team_status(self._team(5)).partial)

    def test_team_status_ignores_strict_preference(self):
        adj = self._adj(0)
        self._judge(adj, 1)
        self._assign(adj, team=self._team(4))
        strict_status = self._info(min_rounds=2, strict=True).team_status(self._team(4))
        nonstrict_status = self._info(min_rounds=2, strict=False).team_status(self._team(4))
        self.assertEqual(strict_status.compliant, nonstrict_status.compliant)
        self.assertEqual(strict_status.coverage, nonstrict_status.coverage)

    def test_all_independent_team_statuses_excludes_institution_teams(self):
        info = self._info()
        teams = {status.team for status in info.all_independent_team_statuses()}
        self.assertEqual(teams, {self._team(4), self._team(5)})

    # ==========================================================================
    # Exception model behaviour
    # ==========================================================================

    def test_exceptions_scoped_per_tournament(self):
        Team.objects.create(tournament=self.other_tournament, institution=self.alpha, reference=100)
        self._except(1, tournament=self.tournament, institution=self.alpha)
        self._except(5, tournament=self.other_tournament, institution=self.alpha)
        info = self._info(tournament=self.tournament)
        other_info = self._info(tournament=self.other_tournament)
        self.assertEqual(info.institution_status(self.alpha).exceptions_granted, 1)
        self.assertEqual(other_info.institution_status(self.alpha).exceptions_granted, 5)