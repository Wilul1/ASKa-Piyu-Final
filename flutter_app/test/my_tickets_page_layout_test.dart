import 'dart:async';
import 'dart:convert';
import 'dart:io';

import 'package:aska_piyu/auth/auth_state.dart';
import 'package:aska_piyu/models/auth_models.dart';
import 'package:aska_piyu/screens/my_tickets_page.dart';
import 'package:aska_piyu/services/auth_service.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

const _automaticLabel = 'Automatic routing — Let ASKa-Piyu choose';

void main() {
  setUp(() {
    HttpOverrides.global = _TicketsHttpOverrides();
  });

  tearDown(() {
    HttpOverrides.global = null;
  });

  testWidgets('desktop my tickets matches the browse layout', (tester) async {
    await _pumpTickets(tester, const Size(1648, 928));

    expect(find.text('My Tickets'), findsWidgets);
    expect(find.text('Track the status of your support tickets.'), findsOneWidget);
    expect(find.widgetWithText(ElevatedButton, 'Submit Ticket'), findsOneWidget);
    expect(find.text('Open'), findsWidgets);
    expect(find.text('In Progress'), findsWidgets);
    expect(find.text('Closed'), findsWidgets);
    expect(find.text('Total'), findsOneWidget);
    expect(find.text('Awaiting office response'), findsOneWidget);
    expect(find.text('Being handled by the office'), findsOneWidget);
    expect(find.text('Resolved tickets'), findsOneWidget);
    expect(find.text('All time tickets'), findsOneWidget);
    expect(
      find.text('Search ticket ID, subject, office, or category...'),
      findsOneWidget,
    );
    expect(find.text('All Status'), findsOneWidget);
    expect(find.text('All Offices'), findsOneWidget);
    expect(find.text('All Categories'), findsOneWidget);
    expect(find.text('Clear'), findsOneWidget);
    expect(find.text('TK-20261020-D90242'), findsOneWidget);
    expect(find.text('TK-20261007-0566FE'), findsOneWidget);
    expect(find.text('Ask Assistant'), findsOneWidget);
    expect(find.text('Mailbox'), findsOneWidget);
    expect(find.text('Account'), findsOneWidget);
    expect(find.byIcon(Icons.home), findsOneWidget);
    expect(find.text('6'), findsOneWidget);
    expect(find.text('8'), findsOneWidget);

    await tester.enterText(find.byType(TextField), '0566FE');
    await tester.pumpAndSettle();
    expect(find.text('TK-20261007-0566FE'), findsOneWidget);
    expect(find.text('TK-20261020-D90242'), findsNothing);

    await tester.tap(find.text('Clear'));
    await tester.pumpAndSettle();
    expect(find.text('TK-20261020-D90242'), findsOneWidget);

    await tester.tap(find.text('All Status'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('In Progress').last);
    await tester.pumpAndSettle();
    expect(find.text('TK-20261007-0566FE'), findsOneWidget);
    expect(find.text('TK-20261020-D90242'), findsNothing);

    await tester.tap(find.text('Clear'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('TK-20261020-D90242'));
    await tester.pumpAndSettle();
    expect(find.byType(TicketDetailsPage), findsOneWidget);
    tester.state<NavigatorState>(find.byType(Navigator)).pop();
    await tester.pumpAndSettle();
    await tester.tap(find.widgetWithText(ElevatedButton, 'Submit Ticket'));
    await tester.pumpAndSettle();
    expect(find.text('Submit a Support Request'), findsOneWidget);
    expect(find.text('Tell us what you need help with.'), findsOneWidget);
    expect(find.text('Before submitting'), findsOneWidget);
    expect(find.text('Tips for a faster response:'), findsOneWidget);
    expect(find.text('Enter a short subject'), findsOneWidget);
    expect(find.text('Describe your concern'), findsOneWidget);
    expect(find.text('Cancel'), findsOneWidget);
    expect(find.text(_automaticLabel), findsOneWidget);

    await tester.enterText(find.byType(TextFormField).first, 'Need transcript copy');
    await tester.enterText(
      find.byType(TextFormField).last,
      'I already visited the Registrar last week and still need a certified copy.',
    );
    await tester.tap(
      find.descendant(
        of: find.byType(CreateTicketForm),
        matching: find.text('Submit Ticket'),
      ),
    );
    await tester.pumpAndSettle();
    expect(find.text('Ticket submitted successfully.'), findsOneWidget);
    expect(find.text('Track the status of your support tickets.'), findsOneWidget);

    await tester.tap(find.widgetWithText(ElevatedButton, 'Submit Ticket'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Cancel'));
    await tester.pumpAndSettle();
    expect(find.text('Track the status of your support tickets.'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('mobile my tickets stacks without overflow', (tester) async {
    await _pumpTickets(tester, const Size(390, 844));

    expect(find.text('My Tickets'), findsWidgets);
    expect(find.text('Submit Ticket'), findsWidgets);
    expect(find.text('TK-20261020-D90242'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });
}

Future<void> _pumpTickets(WidgetTester tester, Size size) async {
  tester.view.physicalSize = size;
  tester.view.devicePixelRatio = 1;
  addTearDown(tester.view.resetPhysicalSize);
  addTearDown(tester.view.resetDevicePixelRatio);

  final controller = AuthController(service: _FakeAuthService());
  await controller.login(
    const LoginRequest(email: 'student@example.edu', password: 'password'),
  );

  await tester.pumpWidget(
    AuthScope(
      controller: controller,
      child: const MaterialApp(home: MyTicketsPage()),
    ),
  );
  await tester.pumpAndSettle();
}

class _FakeAuthService extends AuthService {
  String? _token;

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
    return const AuthResponse(
      accessToken: 'token-student',
      tokenType: 'bearer',
      user: AuthUser(
        id: 'student-1',
        email: 'student@example.edu',
        fullName: 'Test Student',
        role: 'student',
        officeId: null,
        officeName: null,
        emailVerified: true,
        createdAt: null,
        updatedAt: null,
      ),
    );
  }
}

class _TicketsHttpOverrides extends HttpOverrides {
  @override
  HttpClient createHttpClient(SecurityContext? context) => _TicketsHttpClient();
}

class _TicketsHttpClient implements HttpClient {
  @override
  Future<HttpClientRequest> openUrl(String method, Uri url) async {
    return _TicketsRequest(method, url);
  }

  @override
  dynamic noSuchMethod(Invocation invocation) => null;
}

class _TicketsRequest implements HttpClientRequest {
  _TicketsRequest(this.method, this.url);

  final String method;
  final Uri url;

  @override
  final HttpHeaders headers = _TicketsHeaders();

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
  Future<HttpClientResponse> close() async =>
      _TicketsResponse(_bytesFor(method, url));

  @override
  dynamic noSuchMethod(Invocation invocation) => null;
}

class _TicketsResponse extends Stream<List<int>> implements HttpClientResponse {
  _TicketsResponse(this._bytes);

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
  HttpHeaders get headers => _TicketsHeaders();

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

class _TicketsHeaders implements HttpHeaders {
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

List<int> _bytesFor(String method, Uri url) {
  final path = url.path;
  if (method.toUpperCase() == 'POST' && path.endsWith('/tickets')) {
    return utf8.encode(
      jsonEncode(_ticket('TK-NEW-SUBMITTED', 'Open')),
    );
  }
  if (path.endsWith('/tickets/notifications')) {
    return utf8.encode(jsonEncode({'items': <Map>[], 'unread_count': 0}));
  }
  if (path.endsWith('/tickets/offices')) {
    return utf8.encode(
      jsonEncode({
        'items': [
          {'id': 'office-registrar', 'name': 'Registrar'},
        ],
      }),
    );
  }
  if (path.contains('/tickets/TK-')) {
    return utf8.encode(jsonEncode(_ticket(path.split('/').last, 'Open')));
  }
  if (path.endsWith('/tickets')) {
    return utf8.encode(
      jsonEncode({
        'items': [
          _ticket('TK-20261020-D90242', 'Open', created: '2026-10-20T16:32:00Z'),
          _ticket('TK-OPEN-2', 'Open'),
          _ticket('TK-OPEN-3', 'Open'),
          _ticket('TK-OPEN-4', 'Open'),
          _ticket('TK-OPEN-5', 'Open'),
          _ticket('TK-OPEN-6', 'Open'),
          _ticket(
            'TK-20261007-0566FE',
            'In Progress',
            created: '2026-10-16T19:39:00Z',
            office: 'Guidance',
            category: 'Counseling',
          ),
          _ticket('TK-CLOSED-1', 'Closed'),
        ],
      }),
    );
  }
  return utf8.encode('{"detail":"not found"}');
}

Map<String, dynamic> _ticket(
  String id,
  String status, {
  String created = '2026-10-12T14:58:00Z',
  String office = 'Registrar',
  String category = 'Admissions',
}) {
  return {
    'ticket_id': id,
    'original_question': 'Need help with $id',
    'status': status,
    'created_at': created,
    'updated_at': created,
    'category': category,
    'assigned_office_name': office,
    'priority': 'Low',
    'description': 'Published ticket summary',
    'messages': <Map>[],
    'attachments': <Map>[],
  };
}
