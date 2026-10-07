// Unit tests for mergeVerifiedCitationsIntoSources, the pure merge
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
// merge, that the merge only ever touches the display-text fields the poll
// response actually returns, and that the one case this fix does not
// change (an answer mode that defers ALL citation data to this poll and
// starts with zero sources) still ends up showing the verified citations,
// exactly as before this fix.

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
  group('mergeVerifiedCitationsIntoSources — non-empty existing sources', () {
    test(
        'preserves documentId/sourceViewUrl/sourcePageUrl/pdfAvailable and '
        'updates title/sourceSection/sourceFilename from the verified citation',
        () {
      final initial = _initialSourceJson();
      expect(_canOpenSourceFromJson(initial), isTrue); // sanity check on the fixture

      final verified = [
        {
          'citation_id': 'cit-abc123',
          'title': 'Foreword (verified)',
          'source_section': 'Foreword Section',
          'source_filename': 'LSPU Student Handbook.pdf',
        },
      ];

      final merged = mergeVerifiedCitationsIntoSources([initial], verified);
      expect(merged, hasLength(1));
      final result = merged.single;

      // Source-viewing fields the poll response never carries: untouched.
      expect(result['document_id'], 'doc-abc123');
      expect(result['source_view_url'],
          '/documents/doc-abc123/source?page=5#page=5');
      expect(
          result['source_page_url'], '/documents/doc-abc123/source/page/5?end=6');
      expect(result['pdf_available'], true);

      // Text fields the poll response does carry: updated.
      expect(result['title'], 'Foreword (verified)');
      expect(result['source_section'], 'Foreword Section');
      expect(result['source_filename'], 'LSPU Student Handbook.pdf');

      // The merged result would still make _QaSource.canOpenSource true.
      expect(_canOpenSourceFromJson(result), isTrue);
    });

    test(
        'a source with no matching verified citation (including no '
        'citationId at all) is returned unchanged, same order preserved',
        () {
      final first = _initialSourceJson();
      final second = Map<String, dynamic>.from(_initialSourceJson())
        ..['citation_id'] = 'cit-other'
        ..['document_id'] = 'doc-other';
      final third = Map<String, dynamic>.from(_initialSourceJson())
        ..remove('citation_id'); // no citationId at all

      final verified = [
        {'citation_id': 'cit-other', 'title': 'Other (verified)'},
      ];

      final merged =
          mergeVerifiedCitationsIntoSources([first, second, third], verified);

      expect(merged, hasLength(3));
      expect(merged[0], equals(first)); // no match -> unchanged
      expect(merged[1]['title'], 'Other (verified)'); // matched -> updated
      expect(merged[1]['document_id'], 'doc-other'); // preserved
      expect(merged[2], equals(third)); // no citationId -> unchanged
    });

    test('a blank/missing text field in the verified citation never '
        'overwrites an existing non-blank value', () {
      final initial = _initialSourceJson();
      final verified = [
        {
          'citation_id': 'cit-abc123',
          'title': '',
          'source_section': null,
          // source_filename key entirely absent
        },
      ];

      final merged =
          mergeVerifiedCitationsIntoSources([initial], verified).single;

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

      final verified = [
        {'citation_id': 'cit-abc123', 'title': 'Foreword (verified)'},
      ];
      final merged =
          mergeVerifiedCitationsIntoSources([initial], verified).single;

      expect(merged['title'], 'Foreword (verified)');
      expect(merged['pdf_available'], false);
      expect(_canOpenSourceFromJson(merged), isFalse);
    });
  });

  group('mergeVerifiedCitationsIntoSources — empty existing sources', () {
    test(
        'falls back to the verified citations themselves when there were no '
        'sources to merge onto (e.g. an answer mode that defers all citation '
        'data to this poll) -- same fallback behavior as before this fix',
        () {
      final verified = [
        {
          'citation_id': 'cit-xyz',
          'title': 'Enrollment',
          'source_section': 'Enrollment',
          'source_filename': 'Laguna State Polytechnic University-CC_2026-1st Edition.pdf',
        },
      ];

      final merged = mergeVerifiedCitationsIntoSources([], verified);

      expect(merged, hasLength(1));
      expect(merged.single['citation_id'], 'cit-xyz');
      expect(merged.single['title'], 'Enrollment');
      // Correctly has no source-viewing fields -- the poll never carries
      // them -- matching the pre-fix fallback exactly (not a regression
      // introduced by this fix; this case was never source-viewable).
      expect(merged.single['document_id'], isNull);
    });

    test('empty existing sources and empty verified citations stay empty',
        () {
      final merged = mergeVerifiedCitationsIntoSources([], const []);
      expect(merged, isEmpty);
    });
  });
}
