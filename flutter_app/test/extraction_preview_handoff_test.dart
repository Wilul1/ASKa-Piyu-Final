import 'package:flutter_test/flutter_test.dart';

import 'package:aska_piyu/services/extraction_preview_store.dart';

void main() {
  Map<String, dynamic> sampleExtractResponse({
    List<Map<String, dynamic>>? units,
    List<Map<String, dynamic>>? v2Services,
  }) {
    return {
      'document_type': 'citizen_charter',
      'document_profile': 'citizen_charter',
      'detected_document_type': {
        'document_type': 'citizen_charter',
        'reason': 'test',
      },
      'parser_document_type': 'citizen_charter',
      'source_type': "Citizen's Charter",
      'review_text': '4. ID Validation\nOffice or Division: OSAS',
      'cleaned_text': '4. ID Validation\nOffice or Division: OSAS',
      'extracted_text': '4. ID Validation\nOffice or Division: OSAS',
      'knowledge_units': units ??
          [
            {
              'unit_index': 0,
              'title': 'ID Validation',
              'content': 'Present COR for ID validation.',
              'content_type': 'procedure',
              'hierarchy_path': 'ID Validation',
              'metadata': {'document_type': 'citizen_charter'},
            },
          ],
      'charter_v2_services': v2Services ??
          [
            {
              'service_title': 'ID Validation',
              'office_division': 'OSAS',
              'extraction_quality': 'clean',
              'parser_debug': {
                'raw_service_block': 'x' * 2000,
                'cleaned_service_block': 'y' * 2000,
                'parser_strategy_used': 'geometry_words_v2',
                'extraction_quality': 'clean',
              },
            },
          ],
      'charter_v2_detected_count': 1,
      'charter_v2_clean_count': 1,
      'charter_v2_needs_review_count': 0,
      'charter_v2_low_quality_count': 0,
      'charter_v2_rag_only_count': 0,
      'charter_v2_diagnostics': {
        'v2_attempted': true,
        'pdf_pages_available': true,
        'preview_has_charter_v2_services': true,
        'preview_charter_v2_services_count': 1,
      },
      'structured': {'fields': [], 'formatted_text': 'large'},
      'chunk_preview': [
        {'chunk_index': 0, 'content': 'should be dropped from handoff'},
      ],
      'kb_statistics': {'documents_indexed': 1},
      'validation_report': {'status': 'Ready'},
    };
  }

  test('extraction preview model includes V2 fields', () {
    final preview = buildCompactExtractionPreview(sampleExtractResponse());
    expect(preview['document_profile'], 'citizen_charter');
    expect(preview['parser_document_type'], 'citizen_charter');
    expect(preview['source_type'], "Citizen's Charter");
    expect(preview['knowledge_units'], isA<List>());
    expect((preview['knowledge_units'] as List).length, 1);
    expect(preview['charter_v2_services'], isA<List>());
    expect((preview['charter_v2_services'] as List).first['service_title'],
        'ID Validation');
    expect(preview['charter_v2_detected_count'], 1);
    expect(preview['charter_v2_diagnostics'], isA<Map>());
    expect(
      (preview['charter_v2_diagnostics'] as Map)['v2_attempted'],
      isTrue,
    );
    // Bulky Documents-only fields are not part of the Generate handoff.
    expect(preview.containsKey('structured'), isFalse);
    expect(preview.containsKey('chunk_preview'), isFalse);
    expect(preview.containsKey('kb_statistics'), isFalse);
    // Parser debug blocks are clipped for localStorage.
    final debug = (preview['charter_v2_services'] as List).first['parser_debug']
        as Map;
    expect((debug['raw_service_block'] as String).length <= 401, isTrue);
  });

  test('Generate Articles loads latest extraction preview package', () {
    final package = buildExtractionHandoffPackage(
      extractResponse: sampleExtractResponse(),
      sourceFilename: 'citizen-charter.pdf',
      status: 'Extraction preview is ready.',
    );
    expect(isValidExtractionHandoff(package), isTrue);
    expect(package['source_filename'], 'citizen-charter.pdf');
    expect(package['knowledge_units_count'], 1);
    expect(package['has_charter_v2_services'], isTrue);
    expect(package['charter_v2_services_count'], 1);
    expect(package['document_profile'], 'citizen_charter');

    final preview = package['preview'] as Map<String, dynamic>;
    expect(preview['review_text'], contains('ID Validation'));
    expect((preview['charter_v2_services'] as List).length, 1);

    final debug = extractionHandoffDebugSummary(package);
    expect(debug['has_last_extraction_preview'], isTrue);
    expect(debug['source_filename'], 'citizen-charter.pdf');
    expect(debug['knowledge_units_count'], 1);
    expect(debug['has_charter_v2_services'], isTrue);
    expect(debug['charter_v2_services_count'], 1);
    expect(debug['document_profile'], 'citizen_charter');
  });

  test('Reload from Documents uses latest valid handoff package', () {
    final first = buildExtractionHandoffPackage(
      extractResponse: sampleExtractResponse(),
      sourceFilename: 'old.pdf',
    );
    final second = buildExtractionHandoffPackage(
      extractResponse: sampleExtractResponse(units: [
        {
          'unit_index': 0,
          'title': 'Good Moral',
          'content': 'Request a good moral certificate.',
          'content_type': 'procedure',
          'hierarchy_path': 'Good Moral',
          'metadata': {},
        },
      ]),
      sourceFilename: 'new-charter.pdf',
      status: 'Extraction preview is ready.',
    );
    expect(
      shouldReplaceExtractionHandoff(existing: first, incoming: second),
      isTrue,
    );
    expect(isValidExtractionHandoff(second), isTrue);
    expect(second['source_filename'], 'new-charter.pdf');
    expect(
      ((second['preview'] as Map)['knowledge_units'] as List).first['title'],
      'Good Moral',
    );
  });

  test('empty preview does not overwrite valid preview', () {
    final valid = buildExtractionHandoffPackage(
      extractResponse: sampleExtractResponse(),
      sourceFilename: 'citizen-charter.pdf',
    );
    final empty = {
      'preview': {
        'knowledge_units': [],
        'charter_v2_services': [],
        'review_text': '',
      },
      'source_filename': '',
      'knowledge_units_count': 0,
    };
    expect(isValidExtractionHandoff(empty), isFalse);
    expect(
      shouldReplaceExtractionHandoff(existing: valid, incoming: empty),
      isFalse,
    );
    expect(
      shouldReplaceExtractionHandoff(existing: null, incoming: empty),
      isFalse,
    );
    expect(
      shouldReplaceExtractionHandoff(existing: null, incoming: valid),
      isTrue,
    );
  });

  test('decodeExtractionHandoff accepts dynamic JSON map typing', () {
    final decoded = <dynamic, dynamic>{
      'source_filename': 'citizen-charter.pdf',
      'document_profile': 'citizen_charter',
      'knowledge_units_count': 1,
      'preview': <dynamic, dynamic>{
        'knowledge_units': [
          <dynamic, dynamic>{'title': 'ID Validation', 'content': 'x'},
        ],
        'charter_v2_services': [],
        'review_text': 'ID Validation',
      },
    };
    final package = decodeExtractionHandoff(decoded);
    expect(package, isNotNull);
    expect(isValidExtractionHandoff(package), isTrue);
    expect(package!['source_filename'], 'citizen-charter.pdf');
  });
}
