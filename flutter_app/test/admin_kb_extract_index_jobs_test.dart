import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:aska_piyu/screens/admin_kb_workspace.dart';
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

  // Stage 25 (Part 3): the two Stage 24 preview fields --
  // original_page_text_snippet / proposed_classification -- rendered by
  // _KnowledgeUnitTile inside KbKnowledgeUnitsReviewPanel. Forced wide
  // (>=900 logical px) so the GridView/fixed-aspect-ratio layout -- the
  // one actually at risk of a RenderFlex overflow from unbounded text --
  // is what's under test, not the narrower ListView fallback.
  group('KbKnowledgeUnitsReviewPanel diagnostic display', () {
    Future<void> pumpPanel(
      WidgetTester tester,
      List<Map<String, dynamic>> units,
    ) async {
      await tester.pumpWidget(
        MaterialApp(
          home: Scaffold(
            body: SizedBox(
              width: 1000,
              height: 600,
              child: KbKnowledgeUnitsReviewPanel(
                knowledgeUnits: units,
                fileName: 'handbook.pdf',
              ),
            ),
          ),
        ),
      );
    }

    Map<String, dynamic> suspiciousUnit({
      String? originalSnippet = 'Sec. 9. Indecency and Obscenity. Original page text.',
      String? classification = 'needs review',
    }) {
      return {
        'unit_index': 0,
        'title': 'Minor Offense',
        'content': 'Short extracted content.',
        'content_type': 'disciplinary_rule',
        'hierarchy_path': 'Chapter 6 > Article 1',
        'status': 'Suspicious',
        'suspicious_reasons': ['very_short'],
        'page_start': 78,
        'original_page_text_snippet': originalSnippet,
        'proposed_classification': classification,
      };
    }

    Map<String, dynamic> okUnitOlderShape() {
      // Exactly the pre-Stage-24 shape: no original_page_text_snippet,
      // no proposed_classification keys at all (not even null-valued).
      return {
        'unit_index': 1,
        'title': 'Admission Requirements',
        'content': 'A student seeking admission must comply with requirements.',
        'content_type': 'policy',
        'hierarchy_path': 'Chapter 3 > Admission',
        'status': 'OK',
        'suspicious_reasons': <String>[],
        'page_start': 12,
      };
    }

    testWidgets('diagnostic snippet and suggested classification render when present', (tester) async {
      await pumpPanel(tester, [suspiciousUnit()]);

      expect(find.textContaining('Suggested classification: needs review'), findsOneWidget);
      expect(find.textContaining('Original page text — unverified source context'), findsOneWidget);

      // Not shown until the control is tapped -- no dialog open yet.
      expect(find.text('Sec. 9. Indecency and Obscenity. Original page text.'), findsNothing);

      await tester.tap(find.textContaining('Original page text — unverified source context'));
      await tester.pumpAndSettle();

      expect(find.text('Sec. 9. Indecency and Obscenity. Original page text.'), findsOneWidget);
    });

    testWidgets('tapping the control opens a dialog with the full label and source text', (tester) async {
      await pumpPanel(tester, [suspiciousUnit()]);

      expect(find.byType(Dialog), findsNothing);

      await tester.tap(find.textContaining('Original page text — unverified source context').first);
      await tester.pumpAndSettle();

      expect(find.byType(Dialog), findsOneWidget);
      // The label appears twice once open: once on the (still-visible) tile
      // trigger, once as the dialog's own title.
      expect(find.textContaining('Original page text — unverified source context'), findsNWidgets(2));
      expect(find.text('Sec. 9. Indecency and Obscenity. Original page text.'), findsOneWidget);
    });

    testWidgets('dialog can be closed via the close icon and via the Close button', (tester) async {
      await pumpPanel(tester, [suspiciousUnit()]);

      await tester.tap(find.textContaining('Original page text — unverified source context').first);
      await tester.pumpAndSettle();
      expect(find.byType(Dialog), findsOneWidget);

      await tester.tap(find.byIcon(Icons.close));
      await tester.pumpAndSettle();
      expect(find.byType(Dialog), findsNothing);

      await tester.tap(find.textContaining('Original page text — unverified source context').first);
      await tester.pumpAndSettle();
      expect(find.byType(Dialog), findsOneWidget);

      await tester.tap(find.widgetWithText(OutlinedButton, 'Close'));
      await tester.pumpAndSettle();
      expect(find.byType(Dialog), findsNothing);
    });

    testWidgets('Copy text button copies the complete snippet to the clipboard', (tester) async {
      String? copiedText;
      tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(
        SystemChannels.platform,
        (methodCall) async {
          if (methodCall.method == 'Clipboard.setData') {
            copiedText = (methodCall.arguments as Map)['text'] as String;
          }
          return null;
        },
      );
      addTearDown(() {
        tester.binding.defaultBinaryMessenger.setMockMethodCallHandler(SystemChannels.platform, null);
      });

      // Rendered/copied text is trimmed (pre-existing behavior, unrelated
      // to this dialog), so the fixture is pre-trimmed to match exactly.
      final longSnippet = ('Repeated disciplinary table text. ' * 200).trim();
      await pumpPanel(tester, [suspiciousUnit(originalSnippet: longSnippet)]);

      await tester.tap(find.textContaining('Original page text — unverified source context').first);
      await tester.pumpAndSettle();

      await tester.tap(find.widgetWithText(InkWell, 'Copy text'));
      await tester.pumpAndSettle();

      expect(copiedText, longSnippet, reason: 'the full, untruncated snippet must be copied');
      expect(find.text('Original page text copied'), findsOneWidget);
    });

    testWidgets('missing diagnostic fields render no diagnostic section', (tester) async {
      await pumpPanel(tester, [okUnitOlderShape()]);

      expect(find.textContaining('Original page text'), findsNothing);
      expect(find.textContaining('Suggested classification'), findsNothing);
      // The rest of the tile still renders normally.
      expect(find.text('Admission Requirements'), findsOneWidget);
    });

    testWidgets('empty diagnostic snippet renders no original-page section', (tester) async {
      await pumpPanel(
        tester,
        [suspiciousUnit(originalSnippet: '   ', classification: 'extraction issue')],
      );

      expect(find.textContaining('Original page text'), findsNothing);
      // An empty/whitespace-only snippet must not suppress a genuinely
      // present classification -- the two fields are independent.
      expect(find.textContaining('Suggested classification: extraction issue'), findsOneWidget);
    });

    testWidgets('suggested classification never changes the status chip', (tester) async {
      await pumpPanel(tester, [suspiciousUnit()]);

      expect(find.text('Suspicious'), findsOneWidget);
      expect(find.text('needs review'), findsNothing);
      expect(find.textContaining('Suggested classification'), findsOneWidget);
    });

    testWidgets('long original-page text opens in a scrollable dialog without overflow or truncation', (tester) async {
      // Rendered/copied text is trimmed (pre-existing behavior, unrelated
      // to this dialog), so the fixture is pre-trimmed to match exactly.
      final longSnippet = ('Repeated disciplinary table text. ' * 200).trim();
      await pumpPanel(tester, [suspiciousUnit(originalSnippet: longSnippet)]);

      await tester.tap(find.textContaining('Original page text — unverified source context').first);
      await tester.pumpAndSettle();

      expect(tester.takeException(), isNull, reason: 'opening a long snippet in the dialog must not overflow');
      expect(find.byType(SingleChildScrollView), findsWidgets);
      // The exact, full (untruncated) snippet text is present in the tree.
      expect(find.text(longSnippet), findsOneWidget);

      await tester.tap(find.byIcon(Icons.close));
      await tester.pumpAndSettle();

      expect(tester.takeException(), isNull);
      expect(find.text(longSnippet), findsNothing);
    });

    testWidgets('existing tile content (title, status, page, content snippet) remains visible', (tester) async {
      await pumpPanel(tester, [suspiciousUnit()]);

      expect(find.text('Minor Offense'), findsOneWidget);
      expect(find.text('Chapter 6 > Article 1'), findsOneWidget);
      expect(find.text('Suspicious'), findsOneWidget);
      expect(find.text('Page 78'), findsOneWidget);
      expect(find.text('Short extracted content.'), findsOneWidget);
    });

    testWidgets('older response-shaped unit maps render without exception', (tester) async {
      await pumpPanel(tester, [okUnitOlderShape(), suspiciousUnit()]);

      expect(tester.takeException(), isNull);
      expect(find.text('Admission Requirements'), findsOneWidget);
      expect(find.text('Minor Offense'), findsOneWidget);
    });
  });
}
