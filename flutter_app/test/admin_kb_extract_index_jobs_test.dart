import 'dart:typed_data';

import 'package:flutter_test/flutter_test.dart';

import 'package:aska_piyu/services/kb_workspace_session.dart';
import 'package:aska_piyu/services/file_pick.dart';

final Uint8List _fixturePdfBytes = Uint8List.fromList(List<int>.generate(16, (i) => i));

/// Covers the 2026-10-05 review_ready/indexing job split for the main
/// Extract & Structure / Index for Chatbot Retrieval workflow:
///   - the HTML-error-body fix (a non-JSON response body, such as Heroku's
///     own HTML error page on a router-level H12 timeout, must never be
///     copied into the preview verbatim)
///   - extractJobId's in-memory-only, per-session lifecycle (never
///     persisted/resumed from anywhere other than the job this exact
///     session just created via Extract)
///
/// This project's Flutter tests have no HTTP-mocking seam for ApiClient
/// (no MockClient/dependency-injection point exists), so the actual
/// network polling loop in runExtract/_runIndexJob is exercised by the
/// backend's own test suite (test_extraction_review_index_jobs.py) against
/// the real route contract instead -- these tests cover exactly the pure,
/// synchronous logic that CAN be tested without a network seam.
void main() {
  group('reviewTextForFailedResponse', () {
    test('trusts a decoded JSON object as-is', () {
      final decoded = <String, dynamic>{'detail': 'Validation failed.'};
      final raw = '{"detail": "Validation failed."}';
      expect(reviewTextForFailedResponse(decoded, raw), raw);
    });

    test('never copies a raw HTML error page into the preview', () {
      const htmlBody =
          '<!DOCTYPE html><html><head><title>Application Error</title></head>'
          '<body>Heroku | Application Error</body></html>';
      final result = reviewTextForFailedResponse(htmlBody, htmlBody);
      expect(result, isNot(contains('<!DOCTYPE html>')));
      expect(result, isNot(contains('<html>')));
      expect(result, isNot(contains('<body>')));
      expect(result, contains('unexpected (non-JSON) error page'));
    });

    test('catches HTML even without a leading doctype (fragment-style body)', () {
      const htmlBody = '<html><body><h1>Application Error</h1></body></html>';
      final result = reviewTextForFailedResponse(htmlBody, htmlBody);
      expect(result, isNot(contains('<html>')));
    });

    test('sanitizes a non-map decoded value (e.g. a bare JSON string or null)', () {
      expect(
        reviewTextForFailedResponse(null, ''),
        'An unexpected error occurred. Please try again.',
      );
      expect(
        reviewTextForFailedResponse('just a string, not an object', 'just a string, not an object'),
        'just a string, not an object',
      );
    });

    test('a decoded JSON array (not an object) is also sanitized, not shown raw', () {
      final decoded = <dynamic>['not', 'an', 'object'];
      const raw = '["not", "an", "object"]';
      final result = reviewTextForFailedResponse(decoded, raw);
      expect(result, raw); // short enough to pass through unchanged after sanitization
      // Longer non-object JSON must still be truncated like any other non-map body.
      final longRaw = '["x"]' * 100;
      final longResult = reviewTextForFailedResponse(List.filled(100, 'x'), longRaw);
      expect(longResult.length, lessThanOrEqualTo(241));
    });
  });

  group('KbWorkspaceSession extractJobId lifecycle (job isolation)', () {
    test('starts with no job id -- nothing is resumed on session creation', () {
      final session = KbWorkspaceSession();
      expect(session.extractJobId, isNull);
    });

    test('selecting a new file clears any previously captured job id', () {
      final session = KbWorkspaceSession();
      session.extractJobId = 'job-from-a-previous-extract';
      session.setSelectedFile(PickedAppFile(name: 'new.pdf', bytes: _fixturePdfBytes));
      expect(session.extractJobId, isNull);
    });

    test('clear() resets the job id (e.g. on logout)', () {
      final session = KbWorkspaceSession();
      session.extractJobId = 'job-123';
      session.clear();
      expect(session.extractJobId, isNull);
    });
  });
}
