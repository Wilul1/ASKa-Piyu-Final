import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:aska_piyu/auth/auth_state.dart';
import 'package:aska_piyu/models/auth_models.dart';
import 'package:aska_piyu/models/evaluation_models.dart';
import 'package:aska_piyu/screens/admin_model_evaluation_page.dart';
import 'package:aska_piyu/services/auth_service.dart';
import 'package:aska_piyu/services/evaluation_api.dart' show EvaluationApiException;

Map<String, dynamic> _metricJson(String name, double? value) =>
    {'metric_name': name, 'metric_value': value, 'extra': null};

Map<String, dynamic> _componentJson({
  required String componentId,
  required String component,
  required String status,
  String? reason,
  String? note,
  required String modelName,
  String? sharesModelWith,
  bool? allowLlmFallback,
  int caseCount = 0,
  int skippedUnlabeledCount = 0,
  bool hasConfusionMatrix = false,
  List<Map<String, dynamic>> metrics = const [],
}) {
  return {
    'component_id': componentId,
    'component': component,
    'status': status,
    'reason': reason,
    'note': note,
    'model_name': modelName,
    'shares_model_with': sharesModelWith,
    'allow_llm_fallback': allowLlmFallback,
    'case_count': caseCount,
    'skipped_unlabeled_count': skippedUnlabeledCount,
    'has_confusion_matrix': hasConfusionMatrix,
    'metrics': metrics,
  };
}

List<Map<String, dynamic>> _sampleComponents() {
  return [
    _componentJson(
      componentId: 'c-question',
      component: 'classify_question',
      status: 'evaluated',
      modelName: 'rule+similarity (never calls an LLM)',
      allowLlmFallback: false,
      caseCount: 4,
      skippedUnlabeledCount: 1,
      hasConfusionMatrix: true,
      metrics: [
        _metricJson('accuracy', 1.0),
        _metricJson('macro_f1', 1.0),
        _metricJson('macro_precision', 1.0),
        _metricJson('macro_recall', 1.0),
        {
          'metric_name': 'per_class_breakdown',
          'metric_value': null,
          'extra': [
            {'label': 'Enrollment', 'precision': 1.0, 'recall': 1.0, 'f1': 1.0, 'support': 3},
            {'label': 'Library', 'precision': 1.0, 'recall': 1.0, 'f1': 1.0, 'support': 1},
          ],
        },
      ],
    ),
    _componentJson(
      componentId: 'c-chunk-true',
      component: 'classify_chunk(allow_llm=True)',
      status: 'not_evaluable',
      reason: 'no labeled classify_chunk cases in classification_eval_dataset.json',
      modelName: 'rule+similarity+optional_llm(llama-3.3-70b-versatile)',
      allowLlmFallback: true,
    ),
    _componentJson(
      componentId: 'c-embed',
      component: 'embedding_retrieval',
      status: 'evaluated',
      modelName: 'sentence-transformers: intfloat/multilingual-e5-small',
      caseCount: 3,
      metrics: [_metricJson('embedding_hit_at_k', 0.8), _metricJson('embedding_mrr', 0.7)],
    ),
    _componentJson(
      componentId: 'c-reranker',
      component: 'reranker',
      status: 'evaluated',
      modelName: 'rule-based query expansion + heuristic boosting (not a trained model)',
      caseCount: 3,
      metrics: [
        _metricJson('embedding_hit_at_k', 0.8),
        _metricJson('reranked_hit_at_k', 0.6),
        _metricJson('embedding_mrr', 0.7),
        _metricJson('reranked_mrr', null),
      ],
    ),
    _componentJson(
      componentId: 'c-answer',
      component: 'answer_generation_llm',
      status: 'evaluated',
      modelName: 'llama-3.3-70b-versatile',
      caseCount: 2,
      metrics: [
        _metricJson('avg_latency_ms', 420.5),
        _metricJson('first_call_in_run_avg_latency_ms', 900.0),
        _metricJson('warm_avg_latency_ms', 180.0),
        _metricJson('success_rate', 1.0),
      ],
    ),
    _componentJson(
      componentId: 'c-verifier',
      component: 'citation_verifier_llm',
      status: 'not_evaluable',
      reason: 'gold_citation_ids existed for 2 case(s), but the LLM verifier was never successfully invoked',
      modelName: 'llama-3.3-70b-versatile',
      sharesModelWith: 'answer_generation_llm',
    ),
  ];
}

Map<String, dynamic> _sampleRunDetailJson(String runId, {String status = 'completed'}) {
  return {
    'run_id': runId,
    'status': status,
    'triggered_by_user_id': null,
    'started_at': '2026-11-04T08:00:00+00:00',
    'completed_at': status == 'running' ? null : '2026-11-04T08:05:00+00:00',
    'error_message': null,
    'config': {
      'groq_model': 'llama-3.3-70b-versatile',
      'embedding_model_label': 'sentence-transformers: intfloat/multilingual-e5-small',
      'app_commit': 'abc1234',
      'dataset_versions': {'classification': 'cv1', 'retrieval': 'rv1', 'rag': 'gv1'},
    },
    'components': _sampleComponents(),
  };
}

EvaluationSummary _sampleSummary(String runId) {
  final detailJson = _sampleRunDetailJson(runId);
  return EvaluationSummary.fromJson({
    'latest_run': {
      'run_id': runId,
      'status': 'completed',
      'triggered_by_user_id': null,
      'started_at': '2026-11-04T08:00:00+00:00',
      'completed_at': '2026-11-04T08:05:00+00:00',
      'error_message': null,
    },
    'components': detailJson['components'],
  });
}

AuthUser _adminUser() {
  return const AuthUser(
    id: 'admin-1',
    email: 'admin@example.edu',
    fullName: 'Campus Admin',
    role: 'admin',
    officeId: null,
    officeName: null,
    emailVerified: true,
    createdAt: null,
    updatedAt: null,
  );
}

class _FakeAuthService extends AuthService {
  final AuthUser user;
  String? _token;

  _FakeAuthService(this.user);

  @override
  Future<String?> readAccessToken() async => _token;

  @override
  Future<void> storeAccessToken(String token, {required bool persist}) async {
    _token = token;
  }

  @override
  Future<void> clearAccessToken() async {
    _token = null;
  }

  @override
  Future<AuthResponse> login(LoginRequest payload) async {
    return AuthResponse(accessToken: 'token-${user.role}', tokenType: 'bearer', user: user);
  }

  @override
  Future<AuthUser> getCurrentUser(String token) async => user;
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  Future<void> pumpPage(
    WidgetTester tester, {
    AdminModelEvaluationPage Function()? build,
  }) async {
    final controller = AuthController(service: _FakeAuthService(_adminUser()));
    await controller.login(const LoginRequest(email: 'admin@example.edu', password: 'password'));

    await tester.pumpWidget(
      AuthScope(
        controller: controller,
        child: MaterialApp(home: build == null ? const AdminModelEvaluationPage() : build()),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
  }

  testWidgets('empty state is shown when no evaluation has been run yet', (tester) async {
    await pumpPage(
      tester,
      build: () => AdminModelEvaluationPage(
        debugFetchModels: () async => const [],
        debugFetchSummary: () async => const EvaluationSummary(latestRun: null, components: []),
        debugFetchHistory: ({required limit, required offset}) async =>
            const EvaluationRunHistoryPage(runs: [], total: 0, limit: 20, offset: 0),
      ),
    );

    expect(find.textContaining('No evaluation has been run yet'), findsOneWidget);
    expect(find.byKey(const Key('eval-run-button')), findsNothing);
    expect(find.byKey(const Key('eval-jump-nav')), findsOneWidget);
    expect(find.byKey(const Key('eval-overview-section')), findsOneWidget);
    expect(find.byKey(const Key('eval-retrieval-overview-title')), findsOneWidget);
    expect(find.byKey(const Key('eval-classification-overview-title')), findsOneWidget);
    expect(find.text('Classification'), findsWidgets);
    _expectPendingRagOverview(tester);
  });

  testWidgets('error state shows a friendly message when the summary call fails', (tester) async {
    await pumpPage(
      tester,
      build: () => AdminModelEvaluationPage(
        debugFetchModels: () async => const [],
        debugFetchSummary: () async => throw EvaluationApiException('Backend unreachable.'),
        debugFetchHistory: ({required limit, required offset}) async =>
            const EvaluationRunHistoryPage(runs: [], total: 0, limit: 20, offset: 0),
      ),
    );

    expect(find.byKey(const Key('eval-load-error')), findsOneWidget);
    expect(find.text('Backend unreachable.'), findsOneWidget);
  });

  testWidgets('success state renders overview stats and classification results from real API shapes',
      (tester) async {
    const runId = 'run-1';
    await pumpPage(
      tester,
      build: () => AdminModelEvaluationPage(
        debugFetchModels: () async => [
          EvaluationModelInfo.fromJson({
            'component': 'classify_question',
            'model_name': 'rule+similarity (never calls an LLM)',
            'shares_model_with': null,
            'allow_llm_fallback': false,
          }),
        ],
        debugFetchSummary: () async => _sampleSummary(runId),
        debugFetchHistory: ({required limit, required offset}) async => EvaluationRunHistoryPage.fromJson({
          'runs': [
            {
              'run_id': runId,
              'status': 'completed',
              'triggered_by_user_id': null,
              'started_at': '2026-11-04T08:00:00+00:00',
              'completed_at': '2026-11-04T08:05:00+00:00',
              'error_message': null,
            },
          ],
          'total': 1,
          'limit': 10,
          'offset': 0,
        }),
        debugFetchRunDetail: (id) async => EvaluationRunDetail.fromJson(_sampleRunDetailJson(id)),
        debugFetchConfusionMatrix: ({required runId, required component}) async {
          if (component != 'classify_question') return null;
          return EvaluationConfusionMatrix.fromJson({
            'component': 'classify_question',
            'labels': ['Enrollment', 'Library'],
            'matrix': [
              [3, 0],
              [0, 1],
            ],
            'case_count': 4,
          });
        },
      ),
    );

    // Single continuous report: every section is present at once, no tabs.
    expect(find.byKey(const Key('eval-overview-section')), findsOneWidget);
    expect(find.text('Completed'), findsWidgets);
    expect(find.byKey(const Key('eval-export-button')), findsOneWidget);
    expect(find.text('Retrieval'), findsWidgets);
    expect(find.byKey(const Key('eval-classification-overview-title')), findsOneWidget);
    expect(find.text('Classification'), findsWidgets);
    _expectRagMetricCardsPresent();
    expect(find.byKey(const Key('eval-classification-methodology-notice')), findsNothing);
    expect(
      find.textContaining('Classification labels were generated through two independent AI annotation passes'),
      findsNothing,
    );

    // Classification Results: summary stays visible; only the selected classifier matrix shows.
    expect(find.byKey(const Key('eval-classifier-dropdown')), findsOneWidget);
    expect(find.byKey(const Key('eval-classifier-section-classify_question')), findsOneWidget);
    expect(find.byKey(const Key('eval-classifier-section-classify_chunk(allow_llm=True)')), findsNothing);
    expect(find.byKey(const Key('eval-classifier-section-classify_chunk(allow_llm=False)')), findsNothing);
    expect(find.text('Per-subcategory performance'), findsOneWidget);
    expect(find.text('Enrollment'), findsWidgets);
    expect(find.text('Library'), findsWidgets);
    expect(find.text('Per-question scores'), findsNothing);

    // Performance evaluation is out of scope and was removed as a curated section --
    // no latency/throughput bar charts or "Performance" heading anywhere.
    expect(find.text('Performance'), findsNothing);
    expect(find.textContaining('Answer-generation latency (ms)'), findsNothing);
    expect(find.textContaining('Success rate'), findsNothing);
  });

  testWidgets('Refresh reloads the latest completed evaluation without a Run button', (tester) async {
    const runId = 'run-refresh';
    var summaryCalls = 0;
    await pumpPage(
      tester,
      build: () => AdminModelEvaluationPage(
        debugFetchModels: () async => const [],
        debugFetchSummary: () async {
          summaryCalls += 1;
          return EvaluationSummary.fromJson({
            'latest_run': {
              'run_id': runId,
              'status': 'completed',
              'triggered_by_user_id': null,
              'started_at': '2026-11-04T08:00:00+00:00',
              'completed_at': '2026-11-04T08:05:00+00:00',
              'error_message': null,
            },
            'components': _sampleComponents(),
          });
        },
        debugFetchHistory: ({required limit, required offset}) async =>
            const EvaluationRunHistoryPage(runs: [], total: 0, limit: 20, offset: 0),
        debugFetchRunDetail: (id) async => EvaluationRunDetail.fromJson(_sampleRunDetailJson(id)),
      ),
    );

    expect(find.byKey(const Key('eval-run-button')), findsNothing);
    expect(find.byKey(const Key('eval-refresh-button')), findsOneWidget);
    final before = summaryCalls;
    await tester.tap(find.byKey(const Key('eval-refresh-button')));
    await tester.pumpAndSettle();
    expect(summaryCalls, greaterThan(before));
  });

  testWidgets('confusion matrices tab shows a placeholder for a not_evaluable classification component',
      (tester) async {
    const runId = 'run-3';
    final components = [
      _componentJson(
        componentId: 'c-question',
        component: 'classify_question',
        status: 'not_evaluable',
        reason: 'no labeled classify_question cases in classification_eval_dataset.json',
        modelName: 'rule+similarity (never calls an LLM)',
        allowLlmFallback: false,
      ),
    ];
    final detailJson = {
      'run_id': runId,
      'status': 'completed',
      'triggered_by_user_id': null,
      'started_at': '2026-11-04T08:00:00+00:00',
      'completed_at': '2026-11-04T08:05:00+00:00',
      'error_message': null,
      'config': <String, dynamic>{},
      'components': components,
    };

    await pumpPage(
      tester,
      build: () => AdminModelEvaluationPage(
        debugFetchModels: () async => const [],
        debugFetchSummary: () async => EvaluationSummary.fromJson({
          'latest_run': {
            'run_id': runId,
            'status': 'completed',
            'triggered_by_user_id': null,
            'started_at': '2026-11-04T08:00:00+00:00',
            'completed_at': '2026-11-04T08:05:00+00:00',
            'error_message': null,
          },
          'components': components,
        }),
        debugFetchHistory: ({required limit, required offset}) async =>
            const EvaluationRunHistoryPage(runs: [], total: 0, limit: 20, offset: 0),
        debugFetchRunDetail: (id) async => EvaluationRunDetail.fromJson(detailJson),
      ),
    );

    expect(find.textContaining('Not available (not_evaluable'), findsOneWidget);
  });

  testWidgets('classification report uses saved metrics, census, and matrices',
      (tester) async {
    const runId = 'run-cls';
    final components = [
      _componentJson(
        componentId: 'c-question',
        component: 'classify_question',
        status: 'evaluated',
        modelName: 'rule+similarity (never calls an LLM)',
        caseCount: 37,
        hasConfusionMatrix: true,
        metrics: [
          _metricJson('accuracy', 0.7027),
          _metricJson('macro_f1', 0.5064),
          _metricJson('macro_precision', 0.5265),
          _metricJson('macro_recall', 0.5227),
          {
            'metric_name': 'per_class_breakdown',
            'metric_value': null,
            'extra': [
              {
                'label': 'Transcript of Records',
                'precision': 0.8,
                'recall': 1.0,
                'f1': 0.8889,
                'support': 4,
              },
            ],
          },
        ],
      ),
      _componentJson(
        componentId: 'c-chunk-on',
        component: 'classify_chunk(allow_llm=True)',
        status: 'evaluated',
        modelName: 'rule+similarity+optional_llm',
        allowLlmFallback: true,
        caseCount: 28,
        hasConfusionMatrix: true,
        metrics: [
          _metricJson('accuracy', 0.6429),
          _metricJson('macro_f1', 0.5345),
          _metricJson('macro_precision', 0.5292),
          _metricJson('macro_recall', 0.575),
        ],
      ),
      _componentJson(
        componentId: 'c-chunk-off',
        component: 'classify_chunk(allow_llm=False)',
        status: 'evaluated',
        modelName: 'rule+similarity',
        allowLlmFallback: false,
        caseCount: 28,
        hasConfusionMatrix: true,
        metrics: [
          _metricJson('accuracy', 0.6429),
          _metricJson('macro_f1', 0.5345),
          _metricJson('macro_precision', 0.5292),
          _metricJson('macro_recall', 0.575),
        ],
      ),
    ];
    final detailJson = {
      'run_id': runId,
      'status': 'completed',
      'triggered_by_user_id': null,
      'started_at': '2026-11-04T08:00:00+00:00',
      'completed_at': '2026-11-04T08:05:00+00:00',
      'error_message': null,
      'config': {
        'dataset_versions': {
          'classification': '2026-11-04-v2-independent-ai-annotation-dual-agreement',
          'retrieval': 'rv1',
          'rag': 'gv1',
        },
      },
      'components': components,
    };

    await pumpPage(
      tester,
      build: () => AdminModelEvaluationPage(
        debugFetchModels: () async => const [],
        debugFetchSummary: () async => EvaluationSummary.fromJson({
          'latest_run': {
            'run_id': runId,
            'status': 'completed',
            'triggered_by_user_id': null,
            'started_at': '2026-11-04T08:00:00+00:00',
            'completed_at': '2026-11-04T08:05:00+00:00',
            'error_message': null,
          },
          'components': components,
        }),
        debugFetchHistory: ({required limit, required offset}) async =>
            const EvaluationRunHistoryPage(runs: [], total: 0, limit: 20, offset: 0),
        debugFetchRunDetail: (id) async => EvaluationRunDetail.fromJson(detailJson),
        debugFetchConfusionMatrix: ({required runId, required component}) async {
          return EvaluationConfusionMatrix.fromJson({
            'component': component,
            'labels': ['Transcript of Records', 'Library'],
            'matrix': [
              [2, 1],
              [0, 1],
            ],
            'case_count': 4,
          });
        },
      ),
    );

    expect(find.textContaining('70.27%'), findsWidgets);
    expect(find.textContaining('0.5064'), findsWidgets);
    expect(find.text('96'), findsWidgets);
    expect(find.text('31'), findsWidgets);
    expect(find.byKey(const Key('eval-openrouter-401-notice')), findsNothing);
    expect(
      find.textContaining('The OpenRouter request returned HTTP 401'),
      findsNothing,
    );

    expect(find.byKey(const Key('eval-classifier-dropdown')), findsOneWidget);
    expect(find.byKey(const Key('eval-classifier-section-classify_question')), findsOneWidget);
    expect(find.byKey(const Key('eval-classifier-section-classify_chunk(allow_llm=True)')), findsNothing);
    expect(find.byKey(const Key('eval-classifier-section-classify_chunk(allow_llm=False)')), findsNothing);
    expect(find.text('Transcript of Records'), findsWidgets);
    expect(find.text('0.8889'), findsWidgets);
    expect(find.textContaining('not a valid comparison of LLM effectiveness'), findsNothing);
  });

  testWidgets('overview always shows four RAG metric cards when no answer-generation results exist',
      (tester) async {
    const runId = 'run-no-rag';
    final components = [
      _componentJson(
        componentId: 'c-embed',
        component: 'embedding_retrieval',
        status: 'evaluated',
        modelName: 'sentence-transformers: intfloat/multilingual-e5-small',
        caseCount: 12,
        metrics: [_metricJson('embedding_hit_at_k', 0.8333)],
      ),
      _componentJson(
        componentId: 'c-answer',
        component: 'answer_generation_llm',
        status: 'not_evaluable',
        reason: 'no labeled cases in rag_eval_dataset.json',
        modelName: 'llama-3.3-70b-versatile',
      ),
      _componentJson(
        componentId: 'c-verifier',
        component: 'citation_verifier_llm',
        status: 'not_evaluable',
        reason: 'no labeled cases in rag_eval_dataset.json',
        modelName: 'llama-3.3-70b-versatile',
        sharesModelWith: 'answer_generation_llm',
      ),
    ];
    final detailJson = {
      'run_id': runId,
      'status': 'completed',
      'triggered_by_user_id': null,
      'started_at': '2026-11-04T08:00:00+00:00',
      'completed_at': '2026-11-04T08:05:00+00:00',
      'error_message': null,
      'config': <String, dynamic>{},
      'components': components,
    };

    await pumpPage(
      tester,
      build: () => AdminModelEvaluationPage(
        debugFetchModels: () async => const [],
        debugFetchSummary: () async => EvaluationSummary.fromJson({
          'latest_run': {
            'run_id': runId,
            'status': 'completed',
            'triggered_by_user_id': null,
            'started_at': '2026-11-04T08:00:00+00:00',
            'completed_at': '2026-11-04T08:05:00+00:00',
            'error_message': null,
          },
          'components': components,
        }),
        debugFetchHistory: ({required limit, required offset}) async =>
            const EvaluationRunHistoryPage(runs: [], total: 0, limit: 20, offset: 0),
        debugFetchRunDetail: (id) async => EvaluationRunDetail.fromJson(detailJson),
      ),
    );

    expect(find.byKey(const Key('eval-overview-section')), findsOneWidget);
    expect(find.text('Retrieval'), findsWidgets);
    expect(find.text('Classification'), findsWidgets);
    _expectPendingRagOverview(tester);
  });

  testWidgets('overview RAG cards populate from saved citation_verifier metrics without fabricating scores',
      (tester) async {
    const runId = 'run-rag-scores';
    final components = [
      _componentJson(
        componentId: 'c-answer',
        component: 'answer_generation_llm',
        status: 'evaluated',
        modelName: 'llama-3.3-70b-versatile',
        caseCount: 5,
        metrics: [_metricJson('avg_latency_ms', 250.0)],
      ),
      _componentJson(
        componentId: 'c-verifier',
        component: 'citation_verifier_llm',
        status: 'evaluated',
        modelName: 'llama-3.3-70b-versatile',
        sharesModelWith: 'answer_generation_llm',
        caseCount: 5,
        metrics: [
          _metricJson('answer_correctness', 0.8100),
          _metricJson('faithfulness', 0.7200),
          _metricJson('answer_relevancy', 0.6400),
          _metricJson('citation_set_precision', 0.5500),
        ],
      ),
    ];
    final detailJson = {
      'run_id': runId,
      'status': 'completed',
      'triggered_by_user_id': null,
      'started_at': '2026-11-04T08:00:00+00:00',
      'completed_at': '2026-11-04T08:05:00+00:00',
      'error_message': null,
      'config': <String, dynamic>{},
      'components': components,
    };

    await pumpPage(
      tester,
      build: () => AdminModelEvaluationPage(
        debugFetchModels: () async => const [],
        debugFetchSummary: () async => EvaluationSummary.fromJson({
          'latest_run': {
            'run_id': runId,
            'status': 'completed',
            'triggered_by_user_id': null,
            'started_at': '2026-11-04T08:00:00+00:00',
            'completed_at': '2026-11-04T08:05:00+00:00',
            'error_message': null,
          },
          'components': components,
        }),
        debugFetchHistory: ({required limit, required offset}) async =>
            const EvaluationRunHistoryPage(runs: [], total: 0, limit: 20, offset: 0),
        debugFetchRunDetail: (id) async => EvaluationRunDetail.fromJson(detailJson),
      ),
    );

    _expectRagMetricCardsPresent();
    expect(tester.widget<StatusBadge>(find.byKey(const Key('eval-rag-overview-status'))).status, 'evaluated');
    expect(find.text('0.8100'), findsOneWidget);
    expect(find.text('0.7200'), findsOneWidget);
    expect(find.text('0.6400'), findsOneWidget);
    expect(find.text('0.5500'), findsOneWidget);
    expect(find.text('Evaluated · 5 cases'), findsWidgets);
    expect(
      find.descendant(
        of: find.byKey(const Key('eval-rag-card-answer-correctness')),
        matching: find.text('Not yet evaluated'),
      ),
      findsNothing,
    );
    expect(find.byKey(const Key('eval-rag-case-table-title')), findsNothing);
  });

  testWidgets('human-scored QA cards stay visible without per-question rows', (tester) async {
    const runId = 'run-human-overlay';
    final components = [
      _componentJson(
        componentId: 'c-answer',
        component: 'answer_generation_llm',
        status: 'evaluated',
        note: 'Human-scored live student chatbot screenshots',
        modelName: 'human_live_student_chat',
        caseCount: 12,
        skippedUnlabeledCount: 2,
        metrics: [
          _metricJson('answer_correctness', 0.5833),
          _metricJson('faithfulness', 0.5417),
          _metricJson('answer_relevancy', 0.9167),
          _metricJson('citation_set_precision', 0.9000),
          {
            'metric_name': 'per_case_breakdown',
            'metric_value': null,
            'extra': [
              {
                'case_id': 'aq_01_tor_fee',
                'question': 'How much does it cost to get a copy of my Transcript of Records?',
                'included': true,
                'correctness': {'label': 'pass', 'score': 1.0},
                'faithfulness': {'label': 'faithful', 'score': 1.0},
                'relevance': {'label': 'addressed', 'score': 1.0},
                'citation': {'label': 'no_sources_visible', 'score': null},
                'note': 'Undergraduate P75.00/page matches the Charter.',
              },
            ],
          },
        ],
      ),
    ];

    await pumpPage(
      tester,
      build: () => AdminModelEvaluationPage(
        debugFetchModels: () async => const [],
        debugFetchSummary: () async => EvaluationSummary.fromJson({
          'latest_run': {
            'run_id': runId,
            'status': 'completed',
            'triggered_by_user_id': null,
            'started_at': '2026-11-04T08:00:00+00:00',
            'completed_at': '2026-11-04T08:05:00+00:00',
            'error_message': null,
          },
          'components': components,
        }),
        debugFetchHistory: ({required limit, required offset}) async =>
            const EvaluationRunHistoryPage(runs: [], total: 0, limit: 20, offset: 0),
        debugFetchRunDetail: (id) async => EvaluationRunDetail.fromJson({
          'run_id': runId,
          'status': 'completed',
          'triggered_by_user_id': null,
          'started_at': '2026-11-04T08:00:00+00:00',
          'completed_at': '2026-11-04T08:05:00+00:00',
          'error_message': null,
          'config': <String, dynamic>{},
          'components': components,
        }),
      ),
    );

    expect(find.text('0.5833'), findsOneWidget);
    expect(find.byKey(const Key('eval-rag-case-table-title')), findsNothing);
    expect(find.text('Per-question scores'), findsNothing);
    expect(
      find.textContaining('How much does it cost to get a copy of my Transcript of Records?'),
      findsNothing,
    );
  });

  testWidgets('classifier dropdown switches among the three confusion matrices', (tester) async {
    const runId = 'run-classifier-dropdown';
    final components = [
      _componentJson(
        componentId: 'c-question',
        component: 'classify_question',
        status: 'evaluated',
        modelName: 'rule+similarity (never calls an LLM)',
        allowLlmFallback: false,
        caseCount: 4,
        hasConfusionMatrix: true,
        metrics: [
          _metricJson('accuracy', 1.0),
          _metricJson('macro_f1', 1.0),
        ],
      ),
      _componentJson(
        componentId: 'c-chunk-true',
        component: 'classify_chunk(allow_llm=True)',
        status: 'evaluated',
        modelName: 'rule+similarity+optional_llm',
        allowLlmFallback: true,
        caseCount: 4,
        hasConfusionMatrix: true,
        metrics: [
          _metricJson('accuracy', 0.75),
          _metricJson('macro_f1', 0.70),
        ],
      ),
      _componentJson(
        componentId: 'c-chunk-false',
        component: 'classify_chunk(allow_llm=False)',
        status: 'evaluated',
        modelName: 'rule+similarity',
        allowLlmFallback: false,
        caseCount: 4,
        hasConfusionMatrix: true,
        metrics: [
          _metricJson('accuracy', 0.50),
          _metricJson('macro_f1', 0.40),
        ],
      ),
    ];

    await pumpPage(
      tester,
      build: () => AdminModelEvaluationPage(
        debugFetchModels: () async => const [],
        debugFetchSummary: () async => EvaluationSummary.fromJson({
          'latest_run': {
            'run_id': runId,
            'status': 'completed',
            'triggered_by_user_id': null,
            'started_at': '2026-11-04T08:00:00+00:00',
            'completed_at': '2026-11-04T08:05:00+00:00',
            'error_message': null,
          },
          'components': components,
        }),
        debugFetchHistory: ({required limit, required offset}) async =>
            const EvaluationRunHistoryPage(runs: [], total: 0, limit: 20, offset: 0),
        debugFetchRunDetail: (id) async => EvaluationRunDetail.fromJson({
          'run_id': runId,
          'status': 'completed',
          'triggered_by_user_id': null,
          'started_at': '2026-11-04T08:00:00+00:00',
          'completed_at': '2026-11-04T08:05:00+00:00',
          'error_message': null,
          'config': <String, dynamic>{},
          'components': components,
        }),
      ),
    );

    expect(find.byKey(const Key('eval-classifier-dropdown')), findsOneWidget);
    expect(find.byKey(const Key('eval-classifier-section-classify_question')), findsOneWidget);
    expect(find.byKey(const Key('eval-classifier-section-classify_chunk(allow_llm=True)')), findsNothing);

    await tester.ensureVisible(find.byKey(const Key('eval-classifier-dropdown')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('eval-classifier-dropdown')));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Chunk Classifier — LLM Enabled').last);
    await tester.pumpAndSettle();

    expect(find.byKey(const Key('eval-classifier-section-classify_question')), findsNothing);
    expect(find.byKey(const Key('eval-classifier-section-classify_chunk(allow_llm=True)')), findsOneWidget);
  });

  testWidgets('overview shows retrieval overlay hit rate without per-question rows', (tester) async {
    const runId = 'run-retrieval-overlay';
    final components = [
      _componentJson(
        componentId: 'c-rerank',
        component: 'reranker',
        status: 'evaluated',
        note: 'Scored against the isolated chroma_evaluation corpus.',
        modelName: 'rule-based query expansion + heuristic boosting (not a trained model)',
        caseCount: 12,
        metrics: [
          _metricJson('embedding_hit_at_k', 0.8333),
          _metricJson('reranked_hit_at_k', 0.9167),
          _metricJson('reranked_mrr', 0.8125),
          _metricJson('reranked_ndcg_at_k', 0.7812),
          {
            'metric_name': 'per_case_breakdown',
            'metric_value': null,
            'extra': [
              {
                'case_id': 'rag_benchmark_01',
                'question': 'How much does it cost to get a copy of my Transcript of Records?',
                'embedding_hit': true,
                'reranked_hit': true,
              },
              {
                'case_id': 'rag_benchmark_03',
                'question': 'Which office handles student enrollment?',
                'embedding_hit': false,
                'reranked_hit': true,
              },
              {
                'case_id': 'rag_benchmark_10',
                'question': 'What are the responsibilities of an LSPU faculty member?',
                'embedding_hit': false,
                'reranked_hit': false,
              },
            ],
          },
        ],
      ),
    ];

    await pumpPage(
      tester,
      build: () => AdminModelEvaluationPage(
        debugFetchModels: () async => const [],
        debugFetchSummary: () async => EvaluationSummary.fromJson({
          'latest_run': {
            'run_id': runId,
            'status': 'completed',
            'triggered_by_user_id': null,
            'started_at': '2026-11-04T08:00:00+00:00',
            'completed_at': '2026-11-04T08:05:00+00:00',
            'error_message': null,
          },
          'components': components,
        }),
        debugFetchHistory: ({required limit, required offset}) async =>
            const EvaluationRunHistoryPage(runs: [], total: 0, limit: 20, offset: 0),
        debugFetchRunDetail: (id) async => EvaluationRunDetail.fromJson({
          'run_id': runId,
          'status': 'completed',
          'triggered_by_user_id': null,
          'started_at': '2026-11-04T08:00:00+00:00',
          'completed_at': '2026-11-04T08:05:00+00:00',
          'error_message': null,
          'config': <String, dynamic>{},
          'components': components,
        }),
      ),
    );

    expect(find.text('91.67%'), findsWidgets);
    expect(find.byKey(const Key('eval-retrieval-case-table-title')), findsNothing);
    expect(find.text('Per-question scores'), findsNothing);
    expect(find.text('Embedding · Hit'), findsNothing);
    expect(find.text('Reranked · Miss'), findsNothing);
  });

  testWidgets('QA Evaluation and Citation sections show the empty state when the overview is unavailable',
      (tester) async {
    await pumpPage(
      tester,
      build: () => AdminModelEvaluationPage(
        debugFetchModels: () async => const [],
        debugFetchSummary: () async => const EvaluationSummary(latestRun: null, components: []),
        debugFetchHistory: ({required limit, required offset}) async =>
            const EvaluationRunHistoryPage(runs: [], total: 0, limit: 20, offset: 0),
        debugFetchQaCitationOverview: () async => QaCitationJudgingOverview.fromJson({'available': false}),
      ),
    );

    expect(find.byKey(const Key('eval-qa-judging-empty')), findsOneWidget);
    expect(find.byKey(const Key('eval-citation-judging-empty')), findsOneWidget);
    expect(find.textContaining('not available'), findsWidgets);
  });

  testWidgets('QA Evaluation and Citation sections show real QA and corrected citation validity, never the defective value, and never name provider/model identifiers',
      (tester) async {
    await pumpPage(
      tester,
      build: () => AdminModelEvaluationPage(
        debugFetchModels: () async => const [],
        debugFetchSummary: () async => const EvaluationSummary(latestRun: null, components: []),
        debugFetchHistory: ({required limit, required offset}) async =>
            const EvaluationRunHistoryPage(runs: [], total: 0, limit: 20, offset: 0),
        debugFetchQaCitationOverview: () async => QaCitationJudgingOverview.fromJson({
          'available': true,
          'judge_source': 'ai_evaluator',
          'judges': {
            'primary_model': 'dots-studio/dots-3-note-preview:free',
            'primary_provider': 'AtlasCloud',
            'secondary_model': 'nvidia/nemotron-3-ultra-550b-a55b:free',
            'secondary_provider': 'Nvidia',
          },
          'qa': {
            'dimension_means': {
              'correctness': 2.838709677419355,
              'completeness': 2.6451612903225805,
              'relevance': 3.5806451612903225,
              'faithfulness': 2.435483870967742,
              'overall': 2.875,
            },
            'judged_count': 31,
            'judging_failed_partial_count': 0,
            'eligible_count': 31,
            'excluded_count': 1,
            'judge_disagreement_rate': {'numerator': 18, 'denominator': 31, 'value': 0.5806451612903226},
            'insufficient_evidence': {'total_count': 4, 'judged_count': 4},
            'fallback_vs_genuine_counts': {'genuine': 35, 'fallback': 1},
          },
          'citation': {
            'citation_precision': {'numerator': 78, 'denominator': 86, 'value': 0.9069767441860465},
            'citation_completeness': {'numerator': 220, 'denominator': 345, 'value': 0.6376811594202898},
            'claim_support_rate': {'numerator': 220, 'denominator': 345, 'value': 0.6376811594202898},
            'unsupported_claim_rate': {'numerator': 122, 'denominator': 345, 'value': 0.3536231884057971},
            'citation_validity': {'numerator': 86, 'denominator': 86, 'value': 1.0},
            'citation_validity_original_defective': {'numerator': 0, 'denominator': 86, 'value': 0.0},
            'judged_case_count': 30,
            'judging_failed_partial_count': 1,
          },
          'capture_coverage': {'total_cases': 36, 'cases_with_displayed_citations': 34},
          'limitations': ['limitation one', 'limitation two', 'limitation three'],
        }),
      ),
    );

    expect(find.byKey(const Key('eval-qa-section')), findsOneWidget);
    expect(find.byKey(const Key('eval-citation-section')), findsOneWidget);

    // University-appropriate, concise labels -- no "(AI judges)" suffix anywhere.
    // ("QA Evaluation"/"Citation Evaluation" legitimately appear twice each:
    // once as the big section heading, once as the inner sub-header -- both
    // were renamed identically, which is exactly the declutter requested.)
    expect(find.text('QA'), findsWidgets);
    expect(find.text('Automated QA Judging'), findsOneWidget);
    expect(find.text('Citation Evaluation'), findsWidgets);
    expect(find.text('QA Evaluation (AI judges)'), findsNothing);
    expect(find.text('Citation Evaluation (AI judges)'), findsNothing);

    // No provider/model identifiers anywhere in the dashboard, even though
    // the fetched overview data includes them (judges.primary_model etc.).
    expect(find.textContaining('dots-studio/dots-3-note-preview:free'), findsNothing);
    expect(find.textContaining('nvidia/nemotron-3-ultra-550b-a55b:free'), findsNothing);
    expect(find.textContaining('AtlasCloud'), findsNothing);
    expect(find.textContaining('Nvidia'), findsNothing);

    // QA dimension cards render the real means, not fabricated values.
    expect(
      find.descendant(of: find.byKey(const Key('eval-qa-card-overall')), matching: find.text('2.88 / 4')),
      findsOneWidget,
    );
    expect(
      find.descendant(
          of: find.byKey(const Key('eval-qa-card-correctness')), matching: find.text('2.84 / 4')),
      findsOneWidget,
    );

    // Citation validity card shows the CORRECTED 100%, never the original 0%.
    expect(
      find.descendant(of: find.byKey(const Key('eval-citation-card-validity')), matching: find.text('100.0%')),
      findsOneWidget,
    );
    expect(find.text('0.0%'), findsNothing);
    expect(find.textContaining('86/86'), findsWidgets);

    // Correction notes and limitations callouts were removed from the presentation UI.
    expect(find.byKey(const Key('eval-citation-validity-correction-note')), findsNothing);
    expect(find.byKey(const Key('eval-citation-vs-coverage-note')), findsNothing);
    expect(find.byKey(const Key('eval-qa-grounding-limitations')), findsNothing);
    expect(find.textContaining('34/36'), findsNothing);
    expect(find.textContaining('limitation one'), findsNothing);
  });

  testWidgets('QA Evaluation and Citation sections degrade honestly on a load error without blocking the rest of the dashboard',
      (tester) async {
    await pumpPage(
      tester,
      build: () => AdminModelEvaluationPage(
        debugFetchModels: () async => const [],
        debugFetchSummary: () async => const EvaluationSummary(latestRun: null, components: []),
        debugFetchHistory: ({required limit, required offset}) async =>
            const EvaluationRunHistoryPage(runs: [], total: 0, limit: 20, offset: 0),
        debugFetchQaCitationOverview: () async => throw EvaluationApiException('Backend unreachable.'),
      ),
    );

    // The rest of the dashboard still rendered fine.
    expect(find.byKey(const Key('eval-overview-section')), findsOneWidget);

    expect(find.byKey(const Key('eval-qa-judging-error')), findsOneWidget);
    expect(find.byKey(const Key('eval-citation-judging-error')), findsOneWidget);
    expect(find.text('Backend unreachable.'), findsWidgets);
    expect(find.byKey(const Key('eval-qa-judging-retry')), findsOneWidget);
    expect(find.byKey(const Key('eval-citation-judging-retry')), findsOneWidget);
  });

  testWidgets('Overview tab shows the real QA/citation summary, never the defective validity value',
      (tester) async {
    await pumpPage(
      tester,
      build: () => AdminModelEvaluationPage(
        debugFetchModels: () async => const [],
        debugFetchSummary: () async => const EvaluationSummary(latestRun: null, components: []),
        debugFetchHistory: ({required limit, required offset}) async =>
            const EvaluationRunHistoryPage(runs: [], total: 0, limit: 20, offset: 0),
        debugFetchQaCitationOverview: () async => QaCitationJudgingOverview.fromJson({
          'available': true,
          'judge_source': 'ai_evaluator',
          'judges': {
            'primary_model': 'dots-studio/dots-3-note-preview:free',
            'primary_provider': 'AtlasCloud',
            'secondary_model': 'nvidia/nemotron-3-ultra-550b-a55b:free',
            'secondary_provider': 'Nvidia',
          },
          'qa': {
            'dimension_means': {
              'correctness': 2.838709677419355,
              'completeness': 2.6451612903225805,
              'relevance': 3.5806451612903225,
              'faithfulness': 2.435483870967742,
              'overall': 2.875,
            },
            'judged_count': 31,
            'judging_failed_partial_count': 0,
            'eligible_count': 31,
            'excluded_count': 1,
            'judge_disagreement_rate': {'numerator': 18, 'denominator': 31, 'value': 0.5806451612903226},
            'insufficient_evidence': {'total_count': 4, 'judged_count': 4},
            'fallback_vs_genuine_counts': {'genuine': 35, 'fallback': 1},
          },
          'citation': {
            'citation_precision': {'numerator': 78, 'denominator': 86, 'value': 0.9069767441860465},
            'citation_completeness': {'numerator': 220, 'denominator': 345, 'value': 0.6376811594202898},
            'claim_support_rate': {'numerator': 220, 'denominator': 345, 'value': 0.6376811594202898},
            'unsupported_claim_rate': {'numerator': 122, 'denominator': 345, 'value': 0.3536231884057971},
            'citation_validity': {'numerator': 86, 'denominator': 86, 'value': 1.0},
            'citation_validity_original_defective': {'numerator': 0, 'denominator': 86, 'value': 0.0},
            'judged_case_count': 30,
            'judging_failed_partial_count': 1,
          },
          'capture_coverage': {'total_cases': 36, 'cases_with_displayed_citations': 34},
          'limitations': ['limitation one'],
        }),
      ),
    );

    // Overview is the default tab -- no tab switch needed.
    expect(find.byKey(const Key('eval-overview-section')), findsOneWidget);
    expect(find.byKey(const Key('eval-overview-qa-citation-summary')), findsOneWidget);

    expect(
      find.descendant(of: find.byKey(const Key('eval-overview-qa-overall')), matching: find.text('2.88 / 4')),
      findsOneWidget,
    );
    expect(
      find.descendant(
          of: find.byKey(const Key('eval-overview-citation-precision')), matching: find.text('90.7%')),
      findsOneWidget,
    );
    expect(
      find.descendant(
          of: find.byKey(const Key('eval-overview-citation-completeness')), matching: find.text('63.8%')),
      findsOneWidget,
    );
    // Corrected validity, never the defective 0%.
    expect(
      find.descendant(
          of: find.byKey(const Key('eval-overview-citation-validity')), matching: find.text('100.0%')),
      findsOneWidget,
    );
    expect(find.text('0.0%'), findsNothing);

    final overviewCountsText =
        tester.widget<Text>(find.byKey(const Key('eval-overview-qa-citation-counts'))).data!;
    expect(overviewCountsText, contains('31 fully judged answerable cases'));
    expect(overviewCountsText, contains('30 fully judged cases'));
    expect(overviewCountsText, contains('1 partial judging failure'));
  });

  testWidgets('Overview tab QA/citation summary shows the empty callout when unavailable', (tester) async {
    await pumpPage(
      tester,
      build: () => AdminModelEvaluationPage(
        debugFetchModels: () async => const [],
        debugFetchSummary: () async => const EvaluationSummary(latestRun: null, components: []),
        debugFetchHistory: ({required limit, required offset}) async =>
            const EvaluationRunHistoryPage(runs: [], total: 0, limit: 20, offset: 0),
        debugFetchQaCitationOverview: () async => QaCitationJudgingOverview.fromJson({'available': false}),
      ),
    );

    expect(find.byKey(const Key('eval-overview-section')), findsOneWidget);
    expect(find.byKey(const Key('eval-overview-qa-citation-empty')), findsOneWidget);
    expect(find.textContaining('not available'), findsWidgets);
  });

  testWidgets('Overview tab QA/citation summary degrades honestly on a load error, no fabricated numbers',
      (tester) async {
    await pumpPage(
      tester,
      build: () => AdminModelEvaluationPage(
        debugFetchModels: () async => const [],
        debugFetchSummary: () async => const EvaluationSummary(latestRun: null, components: []),
        debugFetchHistory: ({required limit, required offset}) async =>
            const EvaluationRunHistoryPage(runs: [], total: 0, limit: 20, offset: 0),
        debugFetchQaCitationOverview: () async => throw EvaluationApiException('Backend unreachable.'),
      ),
    );

    // The rest of Overview still renders fine; the summary degrades honestly.
    // (Sections 4/5 independently show the same error too -- all three are
    // visible at once now that the report is one continuous page.)
    expect(find.byKey(const Key('eval-overview-section')), findsOneWidget);
    expect(find.byKey(const Key('eval-overview-qa-citation-error')), findsOneWidget);
    expect(find.textContaining('Backend unreachable.'), findsWidgets);
    expect(find.byKey(const Key('eval-overview-qa-citation-summary')), findsNothing);
  });

  testWidgets('the report renders 5 sections plus jump nav, with no methodology or run button', (tester) async {
    await pumpPage(
      tester,
      build: () => AdminModelEvaluationPage(
        debugFetchModels: () async => const [],
        debugFetchSummary: () async => const EvaluationSummary(latestRun: null, components: []),
        debugFetchHistory: ({required limit, required offset}) async =>
            const EvaluationRunHistoryPage(runs: [], total: 0, limit: 20, offset: 0),
      ),
    );

    expect(find.byType(TabBar), findsNothing);
    expect(find.byType(Tab), findsNothing);
    expect(find.byKey(const Key('eval-jump-nav')), findsOneWidget);
    expect(find.byKey(const Key('eval-run-button')), findsNothing);
    expect(find.text('Run Evaluation'), findsNothing);

    const sectionKeys = [
      'eval-section-1-overview',
      'eval-section-2-classification',
      'eval-section-3-retrieval',
      'eval-section-4-qa',
      'eval-section-5-citation',
    ];
    for (final key in sectionKeys) {
      expect(find.byKey(Key(key)), findsOneWidget, reason: 'missing section $key');
    }
    expect(find.byKey(const Key('eval-section-6-methodology')), findsNothing);
    expect(find.byKey(const Key('eval-methodology-section')), findsNothing);
    expect(find.byKey(const Key('eval-section-7-provenance')), findsNothing);

    final offsets = [
      for (final key in sectionKeys) tester.getTopLeft(find.byKey(Key(key))).dy,
    ];
    for (var i = 1; i < offsets.length; i++) {
      expect(offsets[i], greaterThan(offsets[i - 1]), reason: 'section $i is not below section ${i - 1}');
    }
  });

  testWidgets('human-scored live chatbot results stay labeled as human-scored, distinct from automated QA/citation scoring',
      (tester) async {
    const runId = 'run-human-label-check';
    final components = [
      _componentJson(
        componentId: 'c-answer',
        component: 'answer_generation_llm',
        status: 'evaluated',
        note: 'Human-scored live student chatbot screenshots',
        modelName: 'human_live_student_chat',
        caseCount: 12,
        metrics: [_metricJson('answer_correctness', 0.5833), _metricJson('faithfulness', 0.5417)],
      ),
    ];
    await pumpPage(
      tester,
      build: () => AdminModelEvaluationPage(
        debugFetchSummary: () async => EvaluationSummary.fromJson({
          'latest_run': {
            'run_id': runId,
            'status': 'completed',
            'triggered_by_user_id': null,
            'started_at': '2026-11-04T08:00:00+00:00',
            'completed_at': '2026-11-04T08:05:00+00:00',
            'error_message': null,
          },
          'components': components,
        }),
        debugFetchRunDetail: (id) async => EvaluationRunDetail.fromJson({
          'run_id': runId,
          'status': 'completed',
          'triggered_by_user_id': null,
          'started_at': '2026-11-04T08:00:00+00:00',
          'completed_at': '2026-11-04T08:05:00+00:00',
          'error_message': null,
          'config': <String, dynamic>{},
          'components': components,
        }),
        debugFetchQaCitationOverview: () async => QaCitationJudgingOverview.fromJson({
          'available': true,
          'judge_source': 'ai_evaluator',
          'qa': {
            'dimension_means': {'correctness': 2.84, 'completeness': 2.65, 'relevance': 3.58, 'faithfulness': 2.44, 'overall': 2.88},
            'judged_count': 31,
          },
          'citation': {
            'citation_precision': {'numerator': 78, 'denominator': 86, 'value': 0.9069767441860465},
            'citation_validity': {'numerator': 86, 'denominator': 86, 'value': 1.0},
            'judged_case_count': 30,
          },
          'capture_coverage': {'total_cases': 36, 'cases_with_displayed_citations': 34},
          'limitations': <String>[],
        }),
      ),
    );

    // Human-scored QA block stays labeled human-scored.
    expect(find.textContaining('Human-scored from 12 live student chatbot answers'), findsOneWidget);
    expect(find.textContaining('Question-Answering Quality'), findsOneWidget);
    expect(find.text('0.5833'), findsOneWidget);

    // Automated QA / citation blocks stay labeled as automated, not human-scored.
    expect(find.text('Automated QA Judging'), findsOneWidget);
    expect(
      find.descendant(
        of: find.byKey(const Key('eval-qa-grounding-qa-title')),
        matching: find.textContaining('human-scored', findRichText: true),
      ),
      findsNothing,
    );
    expect(
      find.descendant(
        of: find.byKey(const Key('eval-citation-section')),
        matching: find.textContaining('human-scored', findRichText: true),
      ),
      findsNothing,
    );
  });

  testWidgets('Section 7, Run History, Model Inventory, and the full-report JSON download are gone from the dashboard',
      (tester) async {
    const runId = 'run-cleanup-check';
    await pumpPage(
      tester,
      build: () => AdminModelEvaluationPage(
        debugFetchSummary: () async => _sampleSummary(runId),
        debugFetchRunDetail: (id) async => EvaluationRunDetail.fromJson(_sampleRunDetailJson(id)),
        debugFetchConfusionMatrix: ({required runId, required component}) async => null,
      ),
    );

    // Section 7 and everything it held are gone.
    expect(find.byKey(const Key('eval-section-7-provenance')), findsNothing);
    expect(find.byKey(const Key('eval-export-full-report-button')), findsNothing);
    expect(find.text('Download full evaluation report (JSON)'), findsNothing);
    expect(find.byKey(const Key('eval-models-tab')), findsNothing);
    expect(find.text('Model inventory'), findsNothing);
    expect(find.byKey(const Key('eval-results-tab')), findsNothing);
    expect(find.text('Raw per-component results'), findsNothing);
    expect(find.byKey(const Key('eval-history-tab')), findsNothing);
    expect(find.text('Run history'), findsNothing);
    expect(find.byKey(const Key('eval-history-row-$runId')), findsNothing);

    // Out of scope and unaffected: the per-run plain-text report export in
    // Section 1 (Overview) is a different, pre-existing feature from the
    // removed full-report JSON download, and the Refresh/Run Evaluation
    // toolbar keeps working.
    expect(find.byKey(const Key('eval-export-button')), findsOneWidget);
    expect(find.byKey(const Key('eval-refresh-button')), findsOneWidget);
    expect(find.byKey(const Key('eval-run-button')), findsNothing);
    expect(find.byKey(const Key('eval-jump-nav')), findsOneWidget);
  });

  group('responsive rendering of the consolidated report', () {
    const widths = {
      'desktop': Size(1440, 1000),
      'tablet': Size(768, 1100),
      'mobile': Size(390, 1200),
    };

    for (final entry in widths.entries) {
      testWidgets('renders all 5 sections with real data and no exceptions at ${entry.key} width',
          (tester) async {
        tester.view.physicalSize = entry.value;
        tester.view.devicePixelRatio = 1;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);

        const runId = 'run-responsive';
        await pumpPage(
          tester,
          build: () => AdminModelEvaluationPage(
            debugFetchModels: () async => [
              EvaluationModelInfo.fromJson({
                'component': 'classify_question',
                'model_name': 'rule+similarity (never calls an LLM)',
                'shares_model_with': null,
                'allow_llm_fallback': false,
              }),
            ],
            debugFetchSummary: () async => _sampleSummary(runId),
            debugFetchHistory: ({required limit, required offset}) async => EvaluationRunHistoryPage.fromJson({
              'runs': [
                {
                  'run_id': runId,
                  'status': 'completed',
                  'triggered_by_user_id': null,
                  'started_at': '2026-11-04T08:00:00+00:00',
                  'completed_at': '2026-11-04T08:05:00+00:00',
                  'error_message': null,
                },
              ],
              'total': 1,
              'limit': 10,
              'offset': 0,
            }),
            debugFetchRunDetail: (id) async => EvaluationRunDetail.fromJson(_sampleRunDetailJson(id)),
            debugFetchConfusionMatrix: ({required runId, required component}) async => null,
            debugFetchQaCitationOverview: () async => QaCitationJudgingOverview.fromJson({
              'available': true,
              'judge_source': 'ai_evaluator',
              'judges': {
                'primary_model': 'dots-studio/dots-3-note-preview:free',
                'secondary_model': 'nvidia/nemotron-3-ultra-550b-a55b:free',
              },
              'qa': {
                'dimension_means': {'correctness': 2.84, 'completeness': 2.65, 'relevance': 3.58, 'faithfulness': 2.44, 'overall': 2.88},
                'judged_count': 31,
              },
              'citation': {
                'citation_precision': {'numerator': 78, 'denominator': 86, 'value': 0.9069767441860465},
                'citation_validity': {'numerator': 86, 'denominator': 86, 'value': 1.0},
                'judged_case_count': 30,
              },
              'capture_coverage': {'total_cases': 36, 'cases_with_displayed_citations': 34},
              'limitations': <String>[],
            }),
            debugFetchFullReport: () async => <String, dynamic>{},
          ),
        );
        await tester.pumpAndSettle();

        final ex = tester.takeException();
        expect(ex, isNull);
        for (final key in [
          'eval-section-1-overview',
          'eval-section-2-classification',
          'eval-section-3-retrieval',
          'eval-section-4-qa',
          'eval-section-5-citation',
        ]) {
          expect(find.byKey(Key(key)), findsOneWidget, reason: 'missing $key at ${entry.key} width');
        }
        expect(find.byKey(const Key('eval-section-7-provenance')), findsNothing,
            reason: 'Section 7 should not render at ${entry.key} width');
        // A couple of real values confirmed rendered, not just structurally present.
        expect(
          find.descendant(of: find.byKey(const Key('eval-overview-qa-overall')), matching: find.text('2.88 / 4')),
          findsOneWidget,
        );
        expect(
          find.descendant(
              of: find.byKey(const Key('eval-citation-card-validity')), matching: find.text('100.0%')),
          findsOneWidget,
        );
      });
    }
  });
}

void _expectRagMetricCardsPresent() {
  expect(find.byKey(const Key('eval-rag-overview-title')), findsOneWidget);
  expect(find.text('Question-Answering Quality'), findsOneWidget);
  expect(find.byKey(const Key('eval-rag-card-answer-correctness')), findsOneWidget);
  expect(find.byKey(const Key('eval-rag-card-faithfulness')), findsOneWidget);
  expect(find.byKey(const Key('eval-rag-card-answer-relevance')), findsOneWidget);
  expect(find.byKey(const Key('eval-rag-card-citation-accuracy')), findsOneWidget);
  expect(find.text('Answer Correctness'), findsOneWidget);
  expect(find.text('Faithfulness'), findsOneWidget);
  expect(find.text('Answer Relevance'), findsOneWidget);
  expect(find.text('Citation Accuracy'), findsOneWidget);
}

void _expectPendingRagOverview(WidgetTester tester) {
  _expectRagMetricCardsPresent();
  expect(find.byKey(const Key('eval-rag-overview-status')), findsOneWidget);
  expect(tester.widget<StatusBadge>(find.byKey(const Key('eval-rag-overview-status'))).status, 'pending');
  expect(find.text('Pending Evaluation'), findsWidgets);
  expect(find.text('Not yet evaluated'), findsWidgets);
  expect(
    find.descendant(
      of: find.byKey(const Key('eval-rag-card-answer-correctness')),
      matching: find.text('—'),
    ),
    findsOneWidget,
  );
  expect(
    find.descendant(
      of: find.byKey(const Key('eval-rag-card-faithfulness')),
      matching: find.text('—'),
    ),
    findsOneWidget,
  );
  expect(
    find.descendant(
      of: find.byKey(const Key('eval-rag-card-answer-relevance')),
      matching: find.text('—'),
    ),
    findsOneWidget,
  );
  expect(
    find.descendant(
      of: find.byKey(const Key('eval-rag-card-citation-accuracy')),
      matching: find.text('—'),
    ),
    findsOneWidget,
  );
  expect(
    find.descendant(
      of: find.byKey(const Key('eval-rag-card-answer-correctness')),
      matching: find.text('Not yet evaluated'),
    ),
    findsOneWidget,
  );
}
