// Unit tests for mergeVerifiedCitationIntoSourceJson, the pure merge
// extracted from ChatbotPage._pollCitationVerification so it can be tested
// directly without a live Timer, widget tree, or HTTP client (matching the
// precedent in citation_poll_decision_test.dart for evaluateCitationPollTick).
//
// Regression coverage for: the citation-verification poll response
// (GET /qa/citation-verifications/{id}) deliberately carries only
// citation_id/title/source_section/source_filename -- never document_id/
// source_view_url/source_page_url/pdf_available (see
// backend/app/services/qa/citation_verification_jobs.py's _SafeCitation).
// _pollCitationVerification used to replace answer.sources wholesale with
// that minimal payload once verification resolved, which silently zeroed
// out those source-viewing fields and made every verified citation
// non-tappable a few seconds after it first rendered. These tests prove
// the fields a real PDF-viewer-capable citation depends on survive the
// merge, and that the merge only ever touches the display-text fields the
// poll response actually returns.

import 'package:flutter_test/flutter_test.dart';

import 'package:aska_piyu/screens/chatbot_page.dart';

/// Mirrors `_QaSource.canOpenSource`'s boolean logic over a plain JSON map
/// -- `_QaSource` itself is private to chatbot_page.dart and cannot be
/// constructed from this file, so this checks the exact fields that
/// getter depends on, directly on the merge's output.
bool _canOpenSourceFromJson(Map<String, dynamic> json) {
  final viewUrl = (json['source_view_url'] ?? '').toString().trim();
  final pageUrl = (json['source_page_url'] ?? '').toString().trim();
  final documentId = (json['document_id'] ?? '').toString().trim();
  final pdfAvailable = json['pdf_available'];
  return (viewUrl.isNotEmpty || pageUrl.isNotEmpty) &&
      documentId.isNotEmpty &&
      pdfAvailable != false;
}

Map<String, dynamic> _initialSourceJson() => {
      'title': 'Foreword',
      'path': 'Foreword',
      'page': 5,
      'page_number': 5,
      'citation_id': 'cit-abc123',
      'document_id': 'doc-abc123',
      'source_filename': 'LSPU Student Handbook.pdf',
      'source_section': 'Foreword',
      'source_view_url': '/documents/doc-abc123/source?page=5#page=5',
      'source_page_url': '/documents/doc-abc123/source/page/5?end=6',
      'pdf_available': true,
      'citation_note': null,
    };

void main() {
  group('mergeVerifiedCitationIntoSourceJson', () {
    test(
        'preserves documentId/sourceViewUrl/sourcePageUrl/pdfAvailable and '
        'updates title/sourceSection/sourceFilename from the verified citation',
        () {
      final initial = _initialSourceJson();
      expect(_canOpenSourceFromJson(initial), isTrue); // sanity check on the fixture

      final verified = {
        'citation_id': 'cit-abc123',
        'title': 'Foreword (verified)',
        'source_section': 'Foreword Section',
        'source_filename': 'LSPU Student Handbook.pdf',
      };

      final merged = mergeVerifiedCitationIntoSourceJson(initial, verified);

      // Source-viewing fields the poll response never carries: untouched.
      expect(merged['document_id'], 'doc-abc123');
      expect(merged['source_view_url'],
          '/documents/doc-abc123/source?page=5#page=5');
      expect(merged['source_page_url'],
          '/documents/doc-abc123/source/page/5?end=6');
      expect(merged['pdf_available'], true);

      // Text fields the poll response does carry: updated.
      expect(merged['title'], 'Foreword (verified)');
      expect(merged['source_section'], 'Foreword Section');
      expect(merged['source_filename'], 'LSPU Student Handbook.pdf');

      // The merged result would still make _QaSource.canOpenSource true.
      expect(_canOpenSourceFromJson(merged), isTrue);
    });

    test('returns the original JSON unchanged when verifiedCitation is null '
        '(no matching citation_id found during the poll)', () {
      final initial = _initialSourceJson();
      final merged = mergeVerifiedCitationIntoSourceJson(initial, null);
      expect(merged, equals(initial));
      expect(_canOpenSourceFromJson(merged), isTrue);
    });

    test('a blank/missing text field in the verified citation never '
        'overwrites an existing non-blank value', () {
      final initial = _initialSourceJson();
      final verified = {
        'citation_id': 'cit-abc123',
        'title': '',
        'source_section': null,
        // source_filename key entirely absent
      };

      final merged = mergeVerifiedCitationIntoSourceJson(initial, verified);

      expect(merged['title'], 'Foreword');
      expect(merged['source_section'], 'Foreword');
      expect(merged['source_filename'], 'LSPU Student Handbook.pdf');
      expect(_canOpenSourceFromJson(merged), isTrue);
    });

    test('still updates only the returned text fields even when the source '
        'started with pdf_available=false (non-tappable citation stays '
        'non-tappable, but its display text can still refine)', () {
      final initial = Map<String, dynamic>.from(_initialSourceJson())
        ..['pdf_available'] = false
        ..['source_view_url'] = null
        ..['source_page_url'] = null
        ..['document_id'] = null;
      expect(_canOpenSourceFromJson(initial), isFalse);

      final verified = {
        'citation_id': 'cit-abc123',
        'title': 'Foreword (verified)',
      };
      final merged = mergeVerifiedCitationIntoSourceJson(initial, verified);

      expect(merged['title'], 'Foreword (verified)');
      expect(merged['pdf_available'], false);
      expect(_canOpenSourceFromJson(merged), isFalse);
    });
  });
}
