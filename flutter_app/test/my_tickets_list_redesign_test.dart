import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:aska_piyu/screens/my_tickets_page.dart';

/// Covers the My Tickets redesign toward a clean, compact, HESK-style
/// list: trimmed ticket cards (subject, ticket ID, status, last-updated
/// date only -- no priority chip, office/category/reply-count line, or
/// description preview) and a clear "Submit a Ticket" action on the
/// genuinely-empty state. TicketCard and TicketEmptyState are plain,
/// data-in widgets, so these are pumped directly rather than through
/// MyTicketsPage -- there is no HTTP-mocking seam in this codebase's
/// widget tests to seed a populated ticket list through the real page.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  TicketEntry buildTicket({
    String id = 'TK-20261019-ABC123',
    String subject = 'Request for transcript of records',
    String status = 'Open',
    String priority = 'High',
    String category = 'Registrar',
    String assignedOffice = 'Registrar Office',
    String description = 'I need my transcript for a job application.',
    int replyCount = 2,
  }) {
    return TicketEntry(
      id: id,
      userId: 'student-1',
      userName: 'Juan Dela Cruz',
      userEmail: 'student@example.edu',
      subject: subject,
      status: status,
      createdAt: DateTime(2026, 10, 1, 9, 0),
      updatedAt: DateTime(2026, 10, 19, 14, 30),
      resolvedAt: null,
      closedAt: null,
      category: category,
      assignedOffice: assignedOffice,
      priority: priority,
      description: description,
      confidenceScore: null,
      sourceFromChatbot: false,
      messages: [
        for (var i = 0; i < replyCount; i++)
          TicketMessage(
            id: 'msg-$i',
            ticketId: id,
            senderId: 'office-1',
            senderRole: 'office',
            senderName: 'Registrar Staff',
            message: 'Reply $i',
            createdAt: DateTime(2026, 10, 19, 10 + i),
          ),
      ],
    );
  }

  Future<void> pumpCard(WidgetTester tester, TicketEntry ticket) async {
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(body: TicketCard(ticket: ticket, onTap: () {})),
      ),
    );
  }

  // --- Compact card: only subject, ID, status, last-updated date ----------

  testWidgets(
      'the ticket card shows subject, ticket ID, status, and the '
      'last-updated date', (tester) async {
    await pumpCard(tester, buildTicket());

    expect(find.text('Request for transcript of records'), findsOneWidget);
    expect(find.text('TK-20261019-ABC123'), findsOneWidget);
    expect(find.text('Open'), findsOneWidget);
    expect(find.textContaining('Oct 19'), findsOneWidget);
  });

  testWidgets(
      'the ticket card does not show priority, office/category, reply '
      'count, or a description preview -- trimmed for a clean, '
      'non-noisy list', (tester) async {
    await pumpCard(tester, buildTicket());

    expect(find.text('High'), findsNothing);
    expect(find.text('Registrar Office'), findsNothing);
    expect(find.text('Registrar'), findsNothing);
    expect(find.textContaining('replies'), findsNothing);
    expect(find.textContaining('reply'), findsNothing);
    expect(
      find.text('I need my transcript for a job application.'),
      findsNothing,
    );
  });

  testWidgets('the ticket card has no overflow at a narrow phone width',
      (tester) async {
    tester.view.physicalSize = const Size(360, 700);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final unexpectedErrors = <String>[];
    final previousOnError = FlutterError.onError;
    FlutterError.onError = (details) {
      unexpectedErrors.add(details.toString());
      previousOnError?.call(details);
    };
    addTearDown(() => FlutterError.onError = previousOnError);

    await pumpCard(
      tester,
      buildTicket(
        subject:
            'A much longer subject line that could plausibly overflow a '
            'narrow phone-width ticket card if not truncated correctly',
      ),
    );

    expect(unexpectedErrors, isEmpty);
  });

  testWidgets('tapping the card invokes onTap', (tester) async {
    var tapped = false;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: TicketCard(
            ticket: buildTicket(),
            onTap: () => tapped = true,
          ),
        ),
      ),
    );

    await tester.tap(find.text('Request for transcript of records'));
    await tester.pump();

    expect(tapped, isTrue);
  });

  // --- Empty state: clear "Submit a Ticket" action on true empty ----------

  testWidgets(
      'the genuinely-empty state ("No tickets yet") shows a "Submit a '
      'Ticket" action', (tester) async {
    var tapped = false;
    await tester.pumpWidget(
      MaterialApp(
        home: Scaffold(
          body: TicketEmptyState(
            title: 'No tickets yet',
            message: 'Submitted support requests will appear here.',
            onSubmitTicket: () => tapped = true,
          ),
        ),
      ),
    );

    expect(find.text('No tickets yet'), findsOneWidget);
    final button = find.widgetWithText(ElevatedButton, 'Submit a Ticket');
    expect(button, findsOneWidget);

    await tester.tap(button);
    await tester.pump();
    expect(tapped, isTrue);
  });

  testWidgets(
      'the filtered-empty state ("No matching tickets") shows no Submit '
      'a Ticket action -- the student already has tickets', (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: TicketEmptyState(
            title: 'No matching tickets',
            message: 'Try changing the search text, status, or filter.',
          ),
        ),
      ),
    );

    expect(find.text('No matching tickets'), findsOneWidget);
    expect(find.widgetWithText(ElevatedButton, 'Submit a Ticket'), findsNothing);
  });
}
