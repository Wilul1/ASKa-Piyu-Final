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
    expect(find.byKey(const Key('eval-overview-section')), findsOneWidget);
    expect(find.byKey(const Key('eval-retrieval-overview-title')), findsOneWidget);
    expect(find.byKey(const Key('eval-classification-overview-title')), findsOneWidget);
    expect(find.text('Classification Evaluation'), findsOneWidget);
    _expectHumanRagOverlayGone();
    expect(find.byKey(const Key('eval-qa-section')), findsOneWidget);
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
    expect(find.text('Retrieval Evaluation'), findsWidgets);
    expect(find.byKey(const Key('eval-classification-overview-title')), findsOneWidget);
    expect(find.text('Classification Evaluation'), findsOneWidget);
    _expectHumanRagOverlayGone();
    expect(find.byKey(const Key('eval-qa-section')), findsOneWidget);
    expect(find.byKey(const Key('eval-classification-methodology-notice')), findsNothing);
    expect(
      find.textContaining('Classification labels were generated through two independent AI annotation passes'),
      findsNothing,
    );

    // Classification Results section -- unavailable metric is captioned, not silently zero,
    // and each classifier's confusion matrix renders inline.
    expect(find.byKey(const Key('eval-classifier-section-classify_question')), findsOneWidget);
    expect(find.byKey(const Key('eval-classifier-section-classify_chunk(allow_llm=True)')), findsOneWidget);
    expect(find.byKey(const Key('eval-classifier-section-classify_chunk(allow_llm=False)')), findsOneWidget);
    expect(find.textContaining('Not available'), findsWidgets);
    expect(find.text('Per-subcategory performance'), findsWidgets);
    expect(find.text('Enrollment'), findsWidgets);
    expect(find.text('Library'), findsWidgets);

    // Performance evaluation is out of scope and was removed as a curated section --
    // no latency/throughput bar charts or "Performance" heading anywhere.
    expect(find.text('Performance'), findsNothing);
    expect(find.textContaining('Answer-generation latency (ms)'), findsNothing);
    expect(find.textContaining('Success rate'), findsNothing);
  });

  testWidgets('tapping Run Evaluation starts a new run and the new results flow through', (tester) async {
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
    _expectHumanRagOverlayGone();

    await tester.tap(find.byKey(const Key('eval-run-button')));
    await tester.pumpAndSettle();

    expect(startCalls, 1);
    expect(find.text('Running'), findsWidgets);

    await tester.pump(const Duration(seconds: 4));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('eval-classifier-section-classify_question')), findsOneWidget);
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
    expect(find.text('Running'), findsWidgets);

    await tester.pump(const Duration(seconds: 4));
    await tester.pumpAndSettle();
    expect(find.textContaining('TimeoutException'), findsNothing);
    expect(find.text('Running'), findsWidgets);

    await tester.pump(const Duration(seconds: 4));
    await tester.pumpAndSettle();
    expect(find.byKey(const Key('eval-classifier-section-classify_question')), findsOneWidget);
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

    expect(find.byKey(const Key('eval-classifier-section-classify_question')), findsOneWidget);
    expect(find.byKey(const Key('eval-classifier-section-classify_chunk(allow_llm=True)')), findsOneWidget);
    expect(find.byKey(const Key('eval-classifier-section-classify_chunk(allow_llm=False)')), findsOneWidget);
    expect(find.text('Transcript of Records'), findsWidgets);
    expect(find.text('0.8889'), findsWidgets);
    expect(find.textContaining('not a valid comparison of LLM effectiveness'), findsNothing);
  });

  testWidgets('human Answer Generation / RAG overlay is gone; dual-AI QA section remains',
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
        debugFetchQaCitationOverview: () async =>
            QaCitationJudgingOverview.fromJson({'available': false}),
      ),
    );

    expect(find.byKey(const Key('eval-overview-section')), findsOneWidget);
    expect(find.text('Retrieval Evaluation'), findsWidgets);
    expect(find.text('Classification Evaluation'), findsOneWidget);
    _expectHumanRagOverlayGone();
    expect(find.byKey(const Key('eval-qa-section')), findsOneWidget);
    expect(find.byKey(const Key('eval-qa-judging-empty')), findsOneWidget);
    expect(find.text('Answer quality'), findsOneWidget);
    expect(find.text('Not scored'), findsWidgets);
  });

  testWidgets('legacy answer_generation_llm human scores are not rendered as RAG cards',
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
        debugFetchQaCitationOverview: () async =>
            QaCitationJudgingOverview.fromJson({'available': false}),
      ),
    );

    _expectHumanRagOverlayGone();
    expect(find.text('0.8100'), findsNothing);
    expect(find.text('0.7200'), findsNothing);
    expect(find.text('0.6400'), findsNothing);
    expect(find.text('0.5500'), findsNothing);
    expect(find.byKey(const Key('eval-rag-case-table-title')), findsNothing);
  });

  testWidgets('overview shows retrieval overlay hit rate and per-question hits', (tester) async {
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
    expect(find.byKey(const Key('eval-retrieval-case-table-title')), findsOneWidget);
    expect(find.textContaining('How much does it cost to get a copy of my Transcript of Records?'), findsOneWidget);
    expect(find.textContaining('Which office handles student enrollment?'), findsOneWidget);
    expect(find.text('Embedding · Hit'), findsWidgets);
    expect(find.text('Embedding · Miss'), findsWidgets);
    expect(find.text('Reranked · Miss'), findsOneWidget);
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
    expect(find.text('QA Evaluation'), findsWidgets);
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

    // The correction note and the coverage-vs-correctness distinction are both visible.
    expect(find.byKey(const Key('eval-citation-validity-correction-note')), findsOneWidget);
    expect(find.byKey(const Key('eval-citation-vs-coverage-note')), findsOneWidget);
    expect(find.textContaining('34/36'), findsOneWidget);

    expect(find.byKey(const Key('eval-qa-grounding-limitations')), findsOneWidget);
    expect(find.textContaining('limitation one'), findsOneWidget);
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

  testWidgets('the report renders all 6 sections, in order, with no horizontal tabs', (tester) async {
    await pumpPage(
      tester,
      build: () => AdminModelEvaluationPage(
        debugFetchModels: () async => const [],
        debugFetchSummary: () async => const EvaluationSummary(latestRun: null, components: []),
        debugFetchHistory: ({required limit, required offset}) async =>
            const EvaluationRunHistoryPage(runs: [], total: 0, limit: 20, offset: 0),
      ),
    );

    // No TabBar/Tab widgets anywhere -- this is one continuous scroll, not tabs.
    expect(find.byType(TabBar), findsNothing);
    expect(find.byType(Tab), findsNothing);

    const sectionKeys = [
      'eval-section-1-overview',
      'eval-section-2-classification',
      'eval-section-3-retrieval',
      'eval-section-4-qa',
      'eval-section-5-citation',
      'eval-section-6-methodology',
    ];
    for (final key in sectionKeys) {
      expect(find.byKey(Key(key)), findsOneWidget, reason: 'missing section $key');
    }
    // Section 7 (Run Provenance, History, and Raw Results) was removed in
    // the dashboard-cleanup pass, along with the Run History list, Model
    // Inventory cards, raw per-component results, and the full-report
    // JSON download button.
    expect(find.byKey(const Key('eval-section-7-provenance')), findsNothing);

    // Sections appear top-to-bottom in the required 1-6 order.
    final offsets = [
      for (final key in sectionKeys) tester.getTopLeft(find.byKey(Key(key))).dy,
    ];
    for (var i = 1; i < offsets.length; i++) {
      expect(offsets[i], greaterThan(offsets[i - 1]), reason: 'section $i is not below section ${i - 1}');
    }
  });

  testWidgets('Evaluation Methodology section cites real backend file paths for every topic', (tester) async {
    await pumpPage(
      tester,
      build: () => AdminModelEvaluationPage(
        debugFetchModels: () async => const [],
        debugFetchSummary: () async => const EvaluationSummary(latestRun: null, components: []),
        debugFetchHistory: ({required limit, required offset}) async =>
            const EvaluationRunHistoryPage(runs: [], total: 0, limit: 20, offset: 0),
      ),
    );

    expect(find.byKey(const Key('eval-methodology-section')), findsOneWidget);
    expect(find.text('Evaluation Methodology and Computation Process'), findsOneWidget);
    // Each methodology topic's citation strings name a real backend path --
    // this is read from the backend source, never a generic description.
    expect(find.textContaining('backend/app/services/evaluation/'), findsWidgets);
    expect(find.text('Dataset and case selection'), findsOneWidget);
    expect(find.text('Citation validity verification and the Stage 3.6 correction'), findsOneWidget);
    expect(find.text('How run-level metrics are aggregated'), findsOneWidget);
  });

  testWidgets('the compact automated-evaluation disclosure appears exactly once, inside Methodology',
      (tester) async {
    await pumpPage(
      tester,
      build: () => AdminModelEvaluationPage(
        debugFetchSummary: () async => const EvaluationSummary(latestRun: null, components: []),
      ),
    );

    const disclosure = 'QA and citation scores were produced through independent automated '
        'model-based assessments. These results are automated evaluations and '
        'should not be interpreted as human ratings.';
    expect(find.text(disclosure), findsOneWidget);
    expect(
      find.descendant(
        of: find.byKey(const Key('eval-methodology-section')),
        matching: find.byKey(const Key('eval-methodology-automated-disclosure')),
      ),
      findsOneWidget,
    );
  });

  testWidgets('human-scored RAG overlay text is gone while dual-AI QA/citation still render',
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

    _expectHumanRagOverlayGone();
    expect(find.textContaining('Human-scored from 12 live student chatbot answers'), findsNothing);
    expect(find.text('0.5833'), findsNothing);

    expect(find.byKey(const Key('eval-qa-section')), findsOneWidget);
    expect(find.byKey(const Key('eval-citation-section')), findsOneWidget);
    expect(find.byKey(const Key('eval-qa-card-overall')), findsOneWidget);
    expect(
      find.descendant(
        of: find.byKey(const Key('eval-qa-section')),
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
    expect(find.byKey(const Key('eval-run-button')), findsOneWidget);
  });

  group('responsive rendering of the consolidated report', () {
    const widths = {
      'desktop': Size(1440, 1000),
      'tablet': Size(768, 1100),
      'mobile': Size(390, 1200),
    };

    for (final entry in widths.entries) {
      testWidgets('renders all 6 sections with real data and no exceptions at ${entry.key} width',
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
          'eval-section-6-methodology',
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

void _expectHumanRagOverlayGone() {
  expect(find.byKey(const Key('eval-rag-overview-title')), findsNothing);
  expect(find.text('Answer Generation / RAG Evaluation'), findsNothing);
  expect(find.byKey(const Key('eval-rag-card-answer-correctness')), findsNothing);
  expect(find.byKey(const Key('eval-rag-card-faithfulness')), findsNothing);
  expect(find.byKey(const Key('eval-rag-card-answer-relevance')), findsNothing);
  expect(find.byKey(const Key('eval-rag-card-citation-accuracy')), findsNothing);
  expect(find.byKey(const Key('eval-rag-case-table-title')), findsNothing);
  expect(find.textContaining('Human-scored from'), findsNothing);
}
