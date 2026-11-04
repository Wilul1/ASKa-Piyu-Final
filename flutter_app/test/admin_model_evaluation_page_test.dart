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
    expect(find.byKey(const Key('eval-run-button')), findsOneWidget);
    expect(find.byKey(const Key('eval-overview-tab')), findsOneWidget);
    expect(find.byKey(const Key('eval-retrieval-overview-title')), findsOneWidget);
    expect(find.byKey(const Key('eval-classification-overview-title')), findsOneWidget);
    expect(find.text('Classification Evaluation'), findsOneWidget);
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

  testWidgets('success state renders overview stats, models, and component results from real API shapes',
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

    // Overview tab (default): all three evaluation sections stay visible.
    expect(find.byKey(const Key('eval-overview-tab')), findsOneWidget);
    expect(find.text('Completed'), findsWidgets);
    expect(find.byKey(const Key('eval-export-button')), findsOneWidget);
    expect(find.text('Retrieval Evaluation'), findsOneWidget);
    expect(find.byKey(const Key('eval-classification-overview-title')), findsOneWidget);
    expect(find.text('Classification Evaluation'), findsOneWidget);
    _expectRagMetricCardsPresent();
    expect(find.byKey(const Key('eval-classification-methodology-notice')), findsNothing);
    expect(
      find.textContaining('Classification labels were generated through two independent AI annotation passes'),
      findsNothing,
    );

    // Model Inventory tab.
    await tester.tap(find.text('Model Inventory'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('eval-model-classify_question')), findsOneWidget);

    // Component Results tab -- evaluated and not_evaluable statuses both visible.
    await tester.tap(find.text('Component Results'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('eval-result-classify_question')), findsOneWidget);
    expect(find.byKey(const Key('eval-result-classify_chunk(allow_llm=True)')), findsOneWidget);
    expect(find.text('Evaluated'), findsWidgets);
    expect(find.text('Not evaluable'), findsWidgets);
    expect(
      find.text('no labeled classify_chunk cases in classification_eval_dataset.json'),
      findsOneWidget,
    );

    // Comparison tab -- unavailable metric is captioned, not silently zero.
    await tester.tap(find.text('Comparison'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('eval-comparison-tab')), findsOneWidget);
    expect(find.byKey(const Key('eval-classifier-section-classify_question')), findsOneWidget);
    expect(find.byKey(const Key('eval-classifier-section-classify_chunk(allow_llm=True)')), findsOneWidget);
    expect(find.byKey(const Key('eval-classifier-section-classify_chunk(allow_llm=False)')), findsOneWidget);
    expect(find.textContaining('Not available'), findsWidgets);
    expect(find.text('Per-subcategory performance'), findsWidgets);
    expect(find.text('Enrollment'), findsWidgets);

    // Confusion Matrices tab -- only for classify_question, not for other components.
    await tester.tap(find.text('Confusion Matrices'));
    await tester.pumpAndSettle();
    expect(find.text('Enrollment'), findsWidgets);
    expect(find.text('Library'), findsWidgets);

    // Performance tab.
    await tester.tap(find.text('Performance'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('eval-performance-tab')), findsOneWidget);

    // History tab.
    await tester.tap(find.text('History'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('eval-history-row-$runId')), findsOneWidget);
  });

  testWidgets('tapping Run Evaluation starts a new run and switches to Component Results', (tester) async {
    const newRunId = 'run-2';
    var startCalls = 0;
    await pumpPage(
      tester,
      build: () => AdminModelEvaluationPage(
        debugFetchModels: () async => const [],
        debugFetchSummary: () async => const EvaluationSummary(latestRun: null, components: []),
        debugFetchHistory: ({required limit, required offset}) async =>
            const EvaluationRunHistoryPage(runs: [], total: 0, limit: 20, offset: 0),
        debugStartRun: () async {
          startCalls += 1;
          return newRunId;
        },
        debugFetchRunDetail: (id) async => EvaluationRunDetail.fromJson(_sampleRunDetailJson(id)),
        debugFetchConfusionMatrix: ({required runId, required component}) async => null,
      ),
    );

    expect(find.textContaining('No evaluation has been run yet'), findsOneWidget);
    _expectPendingRagOverview(tester);

    await tester.tap(find.byKey(const Key('eval-run-button')));
    await tester.pumpAndSettle();

    expect(startCalls, 1);
    expect(find.text('Evaluation is still running'), findsOneWidget);

    await tester.pump(const Duration(seconds: 4));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('eval-result-classify_question')), findsOneWidget);
  });

  testWidgets('a timed-out run detail fetch keeps polling instead of showing TimeoutException',
      (tester) async {
    const newRunId = 'run-timeout';
    var detailCalls = 0;
    await pumpPage(
      tester,
      build: () => AdminModelEvaluationPage(
        debugFetchModels: () async => const [],
        debugFetchSummary: () async => const EvaluationSummary(latestRun: null, components: []),
        debugFetchHistory: ({required limit, required offset}) async =>
            const EvaluationRunHistoryPage(runs: [], total: 0, limit: 20, offset: 0),
        debugStartRun: () async => newRunId,
        debugFetchRunDetail: (id) async {
          detailCalls += 1;
          if (detailCalls < 2) {
            throw TimeoutException('Future not completed');
          }
          return EvaluationRunDetail.fromJson(_sampleRunDetailJson(id));
        },
        debugFetchConfusionMatrix: ({required runId, required component}) async => null,
      ),
    );

    await tester.tap(find.byKey(const Key('eval-run-button')));
    await tester.pumpAndSettle();
    expect(find.textContaining('TimeoutException'), findsNothing);
    expect(find.text('Evaluation is still running'), findsOneWidget);

    await tester.pump(const Duration(seconds: 4));
    await tester.pumpAndSettle();
    expect(find.textContaining('TimeoutException'), findsNothing);
    expect(find.text('Evaluation is still running'), findsOneWidget);

    await tester.pump(const Duration(seconds: 4));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('eval-result-classify_question')), findsOneWidget);
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

    await tester.ensureVisible(find.text('Confusion Matrices'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Confusion Matrices'));
    await tester.pumpAndSettle();
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

    await tester.ensureVisible(find.text('Comparison'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Comparison'));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('eval-classifier-section-classify_question')), findsOneWidget);
    expect(find.byKey(const Key('eval-classifier-section-classify_chunk(allow_llm=True)')), findsOneWidget);
    expect(find.byKey(const Key('eval-classifier-section-classify_chunk(allow_llm=False)')), findsOneWidget);
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

    expect(find.byKey(const Key('eval-overview-tab')), findsOneWidget);
    expect(find.text('Retrieval Evaluation'), findsOneWidget);
    expect(find.text('Classification Evaluation'), findsOneWidget);
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
  });
}

void _expectRagMetricCardsPresent() {
  expect(find.byKey(const Key('eval-rag-overview-title')), findsOneWidget);
  expect(find.text('Answer Generation / RAG Evaluation'), findsOneWidget);
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
