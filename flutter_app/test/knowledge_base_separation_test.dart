import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('Knowledge Base empty copy refers to published articles, not indexing', () {
    final source = File('lib/screens/knowledge_base_page.dart').readAsStringSync();
    expect(
      source,
      contains(
        'No published Knowledge Base articles yet. Ask an administrator to publish reviewed articles first.',
      ),
    );
    expect(
      source.contains(
        'Categories will appear after Knowledge Base content is indexed.',
      ),
      isFalse,
    );
    expect(
      source,
      contains('Browse published articles by category'),
    );
  });

  test('Admin index action is labeled for chatbot retrieval, not public KB', () {
    final source = File('lib/screens/admin_kb_workspace.dart').readAsStringSync();
    expect(source, contains('Index for Chatbot Retrieval'));
    expect(
      source,
      contains(
        'Indexing stores extracted knowledge units in ChromaDB for Ask ASKa-Piyu retrieval and citation grounding. It does not publish public articles.',
      ),
    );
    expect(source.contains('Index to Knowledge Base'), isFalse);

    final panel = File('lib/screens/admin_panel_page.dart').readAsStringSync();
    expect(panel, contains('Knowledge units indexed for chatbot retrieval.'));
  });

  test('Admin workspace centers Full Extraction Result as main panel', () {
    final source = File('lib/screens/admin_kb_workspace.dart').readAsStringSync();
    expect(source, contains('Full Extraction Result'));
    expect(source, contains('Knowledge Units'));
    expect(source, contains('Processing Status'));
    expect(
      source,
      contains(
        'Scroll inside this panel to review long extractions.',
      ),
    );
    expect(source, contains('_ProcessingStatusRow'));
    expect(source, contains('Expanded(flex: 74'));
    expect(source, contains('Expanded(flex: 26'));
    expect(source, contains('thumbVisibility: true'));
    expect(source, contains('NotificationListener<ScrollNotification>'));
    // Knowledge Units must sit below extraction, not beside it.
    expect(source.contains('Expanded(flex: 28, child: units)'), isFalse);
    expect(source.contains('class _WorkspaceTabs'), isFalse);
    expect(source.contains('Color(0xFF111827)'), isFalse);
  });

  test('public KB article card uses article title, not category', () {
    final source = File('lib/screens/knowledge_base_page.dart').readAsStringSync();
    expect(source, contains("rawTitle.isEmpty ? 'Untitled Article' : rawTitle"));
    expect(source.contains('title: _friendlyArticleTitle('), isFalse);
  });

  test('grouped category view hides duplicate category chips on cards', () {
    final source = File('lib/screens/knowledge_base_page.dart').readAsStringSync();
    expect(source, contains('showCategoryChip: activeCategory == null'));
    expect(source, contains('showCategoryChip'));
    expect(source, contains('addChip(Icons.apartment_outlined, article.office)'));
    expect(source, contains('_documentTypeChipLabel(article)'));
  });
}