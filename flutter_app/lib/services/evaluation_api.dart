/// Thin HTTP layer for the Model Evaluation System admin dashboard.
///
/// Follows the same free-function + ApiClient.send convention already
/// used by admin_management_pages.dart's `_loadAdminOffices` etc. (not
/// the AdminArticleService class style) -- GET via AuthScope's Bearer
/// token, decode JSON, throw on non-2xx. Every response is parsed
/// through models/evaluation_models.dart's fromJson factories, which
/// preserve "null metric_value means not computed" as-is.
library;

import 'dart:convert';

import 'package:flutter/material.dart';

import '../app_config.dart';
import '../auth/auth_state.dart';
import '../models/evaluation_models.dart';
import 'api_client.dart';

/// Thrown by every function below on a non-2xx response. [statusCode] lets
/// callers distinguish an expected 404 (e.g. "this component has no
/// confusion matrix") from a genuine failure.
class EvaluationApiException implements Exception {
  EvaluationApiException(this.message, {this.statusCode});

  final String message;
  final int? statusCode;

  @override
  String toString() => message;
}

Map<String, dynamic> _decodeObject(String body) {
  final text = body.trim();
  if (text.isEmpty) return <String, dynamic>{};
  try {
    final decoded = jsonDecode(text);
    return decoded is Map<String, dynamic> ? decoded : <String, dynamic>{'detail': text};
  } catch (_) {
    return <String, dynamic>{'detail': text};
  }
}

Future<Map<String, dynamic>> _getJson(
  BuildContext context,
  String path, {
  Map<String, String>? query,
  String fallbackError = 'Could not load evaluation data.',
  Duration? timeout,
}) async {
  var uri = Uri.parse('${AppConfig.resolvedApiBase}$path');
  if (query != null && query.isNotEmpty) {
    uri = uri.replace(queryParameters: query);
  }
  final result = await ApiClient.send(
    method: 'GET',
    url: uri.toString(),
    headers: AuthScope.of(context).ticketHeaders(),
    timeout: timeout ?? ApiClient.defaultTimeout,
  );
  final data = _decodeObject(result.body);
  if (!result.ok) {
    throw EvaluationApiException(
      ApiClient.extractError(data, fallback: fallbackError),
      statusCode: result.statusCode,
    );
  }
  return data;
}

Future<List<EvaluationModelInfo>> fetchEvaluationModels(BuildContext context) async {
  final data = await _getJson(context, '/admin/evaluation/models');
  final items = (data['models'] as List?) ?? const [];
  return items
      .whereType<Map>()
      .map((m) => EvaluationModelInfo.fromJson(Map<String, dynamic>.from(m)))
      .toList();
}

Future<EvaluationSummary> fetchEvaluationSummary(BuildContext context) async {
  final data = await _getJson(context, '/admin/evaluation/summary');
  return EvaluationSummary.fromJson(data);
}

Future<EvaluationRunHistoryPage> fetchEvaluationHistory(
  BuildContext context, {
  int limit = 20,
  int offset = 0,
}) async {
  final data = await _getJson(
    context,
    '/admin/evaluation/history',
    query: {'limit': '$limit', 'offset': '$offset'},
  );
  return EvaluationRunHistoryPage.fromJson(data);
}

Future<EvaluationRunDetail> fetchEvaluationRunDetail(BuildContext context, String runId) async {
  final data = await _getJson(
    context,
    '/admin/evaluation/$runId',
    fallbackError: 'Could not load this evaluation run.',
    timeout: const Duration(seconds: 180),
  );
  return EvaluationRunDetail.fromJson(data);
}

Future<String> startEvaluationRun(BuildContext context) async {
  final result = await ApiClient.send(
    method: 'POST',
    url: '${AppConfig.resolvedApiBase}/admin/evaluation/run',
    headers: AuthScope.of(context).ticketHeaders(),
  );
  final data = _decodeObject(result.body);
  if (!result.ok) {
    throw EvaluationApiException(
      ApiClient.extractError(data, fallback: 'Could not start an evaluation run.'),
      statusCode: result.statusCode,
    );
  }
  final runId = data['run_id']?.toString() ?? '';
  if (runId.isEmpty) {
    throw EvaluationApiException('Evaluation run response was missing a run_id.');
  }
  return runId;
}

/// Returns null on a 404 (no confusion matrix for this component -- an
/// expected, non-error outcome for every non-classification component),
/// rethrows any other failure.
Future<EvaluationConfusionMatrix?> fetchEvaluationConfusionMatrix(
  BuildContext context, {
  required String runId,
  required String component,
}) async {
  try {
    final data = await _getJson(
      context,
      '/admin/evaluation/$runId/confusion-matrix',
      query: {'component': component},
      fallbackError: 'Could not load the confusion matrix.',
    );
    return EvaluationConfusionMatrix.fromJson(data);
  } on EvaluationApiException catch (error) {
    if (error.statusCode == 404) return null;
    rethrow;
  }
}

Future<EvaluationCaseResultsPage> fetchEvaluationCaseResults(
  BuildContext context, {
  required String runId,
  required String componentId,
  int limit = 50,
  int offset = 0,
}) async {
  final data = await _getJson(
    context,
    '/admin/evaluation/$runId/components/$componentId/cases',
    query: {'limit': '$limit', 'offset': '$offset'},
    fallbackError: 'Could not load case-level results.',
  );
  return EvaluationCaseResultsPage.fromJson(data);
}
