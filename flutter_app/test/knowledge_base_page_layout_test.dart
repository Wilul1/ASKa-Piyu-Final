import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:aska_piyu/auth/auth_state.dart';
import 'package:aska_piyu/screens/knowledge_base_page.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

void main() {
  setUp(() {
    HttpOverrides.global = _KbHttpOverrides();
  });

  tearDown(() {
    HttpOverrides.global = null;
  });

  testWidgets('desktop knowledge base matches the browse layout', (tester) async {
    await _pumpKb(tester, const Size(1440, 1000));

    expect(find.text('Knowledge Base'), findsWidgets);
    expect(
      find.text(
        'Browse articles, policies, or search for the information you need.',
      ),
      findsOneWidget,
    );
    expect(find.text('Browse by Category'), findsOneWidget);
    expect(
      find.text('Find relevant articles by selecting a category.'),
      findsOneWidget,
    );
    expect(
      find.text('Search articles, policies, or offices...'),
      findsOneWidget,
    );
    expect(find.widgetWithText(ElevatedButton, 'Search'), findsOneWidget);
    expect(find.text('Ask Assistant'), findsOneWidget);
    expect(find.text('My Tickets'), findsOneWidget);
    expect(find.text('Mailbox'), findsNothing);
    expect(find.text('Login'), findsOneWidget);
    expect(find.byIcon(Icons.home), findsOneWidget);

    for (final name in _categoryNames) {
      expect(find.text(name), findsOneWidget);
    }

    await tester.tap(find.text('Admissions'));
    await tester.pumpAndSettle();
    expect(find.text('Admissions guide'), findsOneWidget);

    await tester.tap(find.text('Guidance and Counseling'));
    await tester.pumpAndSettle();
    expect(find.text('Guidance and Counseling guide'), findsOneWidget);

    await tester.enterText(find.byType(TextField), 'tuition');
    await tester.tap(find.widgetWithText(ElevatedButton, 'Search'));
    await tester.pumpAndSettle();
    expect(find.text('Tuition payment policy'), findsOneWidget);
    expect(find.text('Browse by Category'), findsNothing);

    await tester.tap(find.byTooltip('Clear search'));
    await tester.pumpAndSettle();
    expect(find.text('Browse by Category'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('mobile knowledge base stacks without overflow', (tester) async {
    await _pumpKb(tester, const Size(390, 844));

    expect(find.text('Browse by Category'), findsOneWidget);
    expect(find.text('Admissions'), findsOneWidget);
    expect(find.text('ICT Services'), findsOneWidget);
    expect(find.byIcon(Icons.menu_rounded), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}

const _categoryNames = [
  'Admissions',
  'Student Records',
  'Student Services',
  'Guidance and Counseling',
  'Health Services',
  'ICT Services',
];

Future<void> _pumpKb(WidgetTester tester, Size size) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  await tester.pumpWidget(
    AuthScope(
      controller: AuthController(),
      child: const MaterialApp(home: KnowledgeBasePage()),
    ),
  );
  await tester.pumpAndSettle();
}

class _KbHttpOverrides extends HttpOverrides {
  @override
  HttpClient createHttpClient(SecurityContext? context) => _KbHttpClient();
}

class _KbHttpClient implements HttpClient {
  @override
  Future<HttpClientRequest> openUrl(String method, Uri url) async {
    return _KbRequest(url);
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => null;
}

class _KbRequest implements HttpClientRequest {
  _KbRequest(this.url);

  final Uri url;

  @override
  final HttpHeaders headers = _KbHeaders();

  @override
  bool followRedirects = true;

  @override
  int maxRedirects = 5;

  @override
  int contentLength = -1;

  @override
  bool persistentConnection = true;

  @override
  Future<HttpClientRequest> addStream(Stream<List<int>> stream) async {
    await stream.drain<void>();
    return this;
  }

  @override
  void add(List<int> data) {}

  @override
  Future<HttpClientResponse> close() async => _KbResponse(_bytesFor(url));

  @override
  dynamic noSuchMethod(Invocation invocation) => null;
}

class _KbResponse extends Stream<List<int>> implements HttpClientResponse {
  _KbResponse(this._bytes);

  final List<int> _bytes;

  @override
  int get statusCode => 200;

  @override
  int get contentLength => _bytes.length;

  @override
  bool get isRedirect => false;

  @override
  bool get persistentConnection => false;

  @override
  String get reasonPhrase => 'OK';

  @override
  HttpHeaders get headers => _KbHeaders();

  @override
  List<RedirectInfo> get redirects => const [];

  @override
  StreamSubscription<List<int>> listen(
    void Function(List<int> event)? onData, {
    Function? onError,
    void Function()? onDone,
    bool? cancelOnError,
  }) {
    return Stream<List<int>>.value(_bytes).listen(
      onData,
      onError: onError,
      onDone: onDone,
      cancelOnError: cancelOnError,
    );
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => null;
}

class _KbHeaders implements HttpHeaders {
  final Map<String, List<String>> _values = {};

  @override
  void set(String name, Object value, {bool preserveHeaderCase = false}) {
    _values[name.toLowerCase()] = ['$value'];
  }

  @override
  void forEach(void Function(String name, List<String> values) action) {
    _values.forEach(action);
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => null;
}

List<int> _bytesFor(Uri url) {
  final path = url.path;
  if (path.endsWith('/kb/categories')) {
    return utf8.encode(
      jsonEncode({
        'items': [
          for (final name in _categoryNames.reversed)
            {'name': name, 'article_count': 2, 'subcategories': <Map>[]},
        ],
      }),
    );
  }
  if (path.endsWith('/kb/articles')) {
    final query = url.queryParameters['q'] ?? '';
    final category = url.queryParameters['category'] ?? '';
    final title = query.isNotEmpty ? 'Tuition payment policy' : '$category guide';
    return utf8.encode(
      jsonEncode({
        'items': [
          {
            'id': 'art-1',
            'title': title,
            'category': category.isEmpty ? 'Admissions' : category,
            'summary': 'Published article summary',
          },
        ],
        'suggestions': query.isEmpty ? <String>[] : <String>['tuition'],
      }),
    );
  }
  return utf8.encode('{"detail":"not found"}');
}
