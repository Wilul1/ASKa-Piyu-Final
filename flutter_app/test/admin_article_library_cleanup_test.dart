import 'dart:io';

import 'package:flutter_test/flutter_test.dart';

void main() {
  test('Article Library supports unpublish cleanup filters and bulk actions', () {
    final source =
        File('lib/screens/admin_kb_article_library_section.dart').readAsStringSync();
    expect(source, contains('Unpublish Selected'));
    expect(source, contains('Publish Selected'));
    expect(source, contains('bulkUnpublish'));
    expect(
      source,
      contains(
        'They will remain saved as drafts. Continue?',
      ),
    );
    expect(source, contains("label: 'Source document'"));
    expect(source, contains("label: 'Category'"));
    expect(source, contains("label: 'Document type'"));
    expect(source, contains("label: const Text('Needs Review')"));
    expect(source, contains('showPublicReadinessLabels: true'));
  });

  test('Search and Login buttons are text-only', () {
    final kb = File('lib/screens/knowledge_base_page.dart').readAsStringSync();
    final home = File('lib/screens/student_home.dart').readAsStringSync();
    final login = File('lib/screens/login_page.dart').readAsStringSync();
    final sidebar = File('lib/widgets/sidebar.dart').readAsStringSync();

    expect(kb.contains("label: const Text('Search')"), isFalse);
    expect(kb, contains("child: const Text('Search')"));
    expect(home, contains("child: const Text('Search')"));
    expect(login, contains("Text(_loading ? 'Logging in...' : 'Login')"));
    expect(login.contains('Icons.login_rounded'), isFalse);
    expect(sidebar, contains("child: const Text('Login')"));
    expect(sidebar.contains('Icons.login_rounded'), isFalse);
  });
}
