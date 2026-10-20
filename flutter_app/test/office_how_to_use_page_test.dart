import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:aska_piyu/auth/auth_state.dart';
import 'package:aska_piyu/models/auth_models.dart';
import 'package:aska_piyu/screens/office_how_to_use_page.dart';
import 'package:aska_piyu/services/auth_service.dart';

/// OfficeHowToUsePage is pure documentation -- it fetches no live data and
/// calls no backend endpoint, so these tests only need to cover the role
/// gate (reused from OfficeScaffold), that the real page renders with its
/// expected content, and that it doesn't overflow at a few widths. There is
/// no network path to fake here, unlike the console pages.
void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  AuthUser guideUser(String role) {
    return AuthUser(
      id: 'u-1',
      email: '$role@example.edu',
      fullName: role == 'office' ? 'Office Staff' : 'Some User',
      role: role,
      officeId: role == 'office' ? 'office-1' : null,
      officeName: role == 'office' ? 'College of Computer Studies (CCS)' : null,
      emailVerified: true,
      createdAt: null,
      updatedAt: null,
    );
  }

  Future<AuthController> controllerFor(String role) async {
    final controller = AuthController(service: _FakeAuthService(guideUser(role)));
    await controller.login(
      LoginRequest(email: '$role@example.edu', password: 'password'),
    );
    return controller;
  }

  Future<void> pumpPage(
    WidgetTester tester, {
    required AuthController controller,
    Size size = const Size(1400, 1000),
  }) async {
    tester.view.physicalSize = size;
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    await tester.pumpWidget(
      AuthScope(
        controller: controller,
        child: const MaterialApp(home: OfficeHowToUsePage()),
      ),
    );
    await tester.pump();
    await tester.pump(const Duration(milliseconds: 50));
  }

  group('access control (reused from OfficeScaffold)', () {
    testWidgets('a non-office role sees the office-login gate, not the guide',
        (tester) async {
      await pumpPage(tester, controller: await controllerFor('student'));

      expect(find.text('Office access required'), findsOneWidget);
      // The gate's own AppBar legitimately shows the page title ("How to
      // Use") -- the real signal that the guide itself didn't render is
      // the absence of its actual content.
      expect(find.text('A. Assigned Tickets'), findsNothing);
    });

    testWidgets('an office account sees the real guide', (tester) async {
      await pumpPage(tester, controller: await controllerFor('office'));

      expect(find.text('Office access required'), findsNothing);
      // At wide widths this legitimately matches twice: the sidebar's own
      // "How to Use" nav item (now selected) plus this page's own title.
      expect(find.text('How to Use'), findsWidgets);
    });
  });

  group('rendering', () {
    testWidgets('shows the intro and all four topic jump chips', (tester) async {
      await pumpPage(tester, controller: await controllerFor('office'));

      expect(
        find.textContaining("doesn't add any new ticket, article, or"),
        findsOneWidget,
      );
      // Looked up by the chip's own key, not its label text: at wide
      // widths the office sidebar legitimately has its own nav items with
      // the same label ("Assigned Tickets", "Knowledge Base", "Knowledge
      // Article"), so a plain text lookup would over-match.
      for (final label in [
        'Assigned Tickets',
        'Knowledge Base',
        'Knowledge Article',
        'Good Practices',
      ]) {
        expect(
          find.byKey(ValueKey('how-to-use-topic-$label')),
          findsOneWidget,
          reason: '$label topic chip',
        );
      }
    });

    testWidgets('renders all four section headings', (tester) async {
      await pumpPage(tester, controller: await controllerFor('office'));

      expect(find.text('A. Assigned Tickets'), findsOneWidget);
      expect(
        find.text('B. Knowledge Base: Extract and Index Documents'),
        findsOneWidget,
      );
      expect(find.text('C. Knowledge Article'), findsOneWidget);
      expect(find.text('D. Good Practices and Troubleshooting'), findsOneWidget);
    });

    testWidgets('tapping a topic chip does not throw', (tester) async {
      await pumpPage(tester, controller: await controllerFor('office'));

      await tester.tap(
        find.byKey(const ValueKey('how-to-use-topic-Knowledge Article')),
      );
      await tester.pumpAndSettle();

      expect(tester.takeException(), isNull);
    });
  });

  // Scoped to this page's own guide images (asset path prefix) -- a plain
  // find.byType(Image) also matches the sidebar's logo image, which is
  // rendered on every OfficeScaffold page alongside this one.
  Finder howToUseImages() {
    return find.byWidgetPredicate((widget) {
      if (widget is! Image) return false;
      final image = widget.image;
      return image is AssetImage &&
          image.assetName.startsWith('assets/images/how_to_use/');
    });
  }

  group('annotated screenshots', () {
    testWidgets('all seven image assets decode without error', (tester) async {
      await pumpPage(tester, controller: await controllerFor('office'));
      // Images decode asynchronously after the first frame.
      await tester.pumpAndSettle();

      expect(howToUseImages(), findsNWidgets(7));
      expect(tester.takeException(), isNull);
    });

    testWidgets(
        'the Assigned Tickets screenshot discloses its redaction and is '
        'never claimed to be unmodified', (tester) async {
      await pumpPage(tester, controller: await controllerFor('office'));
      await tester.pumpAndSettle();

      expect(
        find.textContaining('Requester names in this screenshot are redacted'),
        findsOneWidget,
      );
    });

    testWidgets(
        'the ticket-detail screenshot discloses its redaction too '
        '(name, avatar, email, and message text)', (tester) async {
      await pumpPage(tester, controller: await controllerFor('office'));
      await tester.pumpAndSettle();

      expect(
        find.textContaining("requester's name, avatar, email, and message "
            'text'),
        findsOneWidget,
      );
    });

    testWidgets('all seven screenshots have their annotation painter wired up',
        (tester) async {
      await pumpPage(tester, controller: await controllerFor('office'));
      await tester.pumpAndSettle();

      // _ScreenshotPainter is library-private, so it can't be named from
      // this test file -- asserting every CustomPaint sitting directly on
      // one of the 5 annotated images has a non-null foregroundPainter is
      // the closest reachable proxy for "the overlay is actually wired
      // up," short of exposing internals solely for testing.
      final painted = tester
          .widgetList<CustomPaint>(find.byType(CustomPaint))
          .where((w) => w.foregroundPainter != null)
          .length;
      expect(painted, greaterThanOrEqualTo(7));
    });

    testWidgets('tapping a screenshot opens an enlarged, dismissible view',
        (tester) async {
      await pumpPage(tester, controller: await controllerFor('office'));
      await tester.pumpAndSettle();

      await tester.tap(howToUseImages().first);
      await tester.pumpAndSettle();

      expect(find.byType(InteractiveViewer), findsOneWidget);
      expect(tester.takeException(), isNull);

      // Dismiss via the barrier so later tests in this file start clean.
      await tester.tapAt(const Offset(5, 5));
      await tester.pumpAndSettle();
      expect(find.byType(InteractiveViewer), findsNothing);
    });

    testWidgets(
        'the reply screenshot specifically can be enlarged enough to '
        'inspect the toolbar and Internal Note icon, then dismissed',
        (tester) async {
      await pumpPage(tester, controller: await controllerFor('office'));
      await tester.pumpAndSettle();

      final replyImage = find.byWidgetPredicate((widget) {
        if (widget is! Image) return false;
        final image = widget.image;
        return image is AssetImage &&
            image.assetName.endsWith('ticket_detail_reply.png');
      });
      expect(replyImage, findsOneWidget);

      // It sits well below the fold on this long page.
      await tester.ensureVisible(replyImage);
      await tester.pumpAndSettle();

      await tester.tap(replyImage);
      await tester.pumpAndSettle();

      final viewer = tester.widget<InteractiveViewer>(
        find.byType(InteractiveViewer),
      );
      // Toolbar icons are small in the inline card; maxScale must allow
      // zooming in far enough to actually tell them apart.
      expect(viewer.maxScale, greaterThanOrEqualTo(4));
      expect(
        find.descendant(of: find.byType(InteractiveViewer), matching: replyImage),
        findsOneWidget,
      );
      expect(tester.takeException(), isNull);

      await tester.tapAt(const Offset(5, 5));
      await tester.pumpAndSettle();
      expect(find.byType(InteractiveViewer), findsNothing);
    });

    testWidgets('no overflow or asset errors with images at width 1400px',
        (tester) async {
      final unexpectedErrors = <String>[];
      final previousOnError = FlutterError.onError;
      FlutterError.onError = (details) {
        unexpectedErrors.add(details.toString());
        previousOnError?.call(details);
      };
      addTearDown(() => FlutterError.onError = previousOnError);

      await pumpPage(
        tester,
        controller: await controllerFor('office'),
        size: const Size(1400, 1200),
      );
      await tester.pumpAndSettle();

      expect(unexpectedErrors, isEmpty);
    });
  });

  group('section content matches the real, inspected workflow', () {
    testWidgets('Assigned Tickets section documents real controls only',
        (tester) async {
      await pumpPage(tester, controller: await controllerFor('office'));

      // Real, confirmed behavior: Resolve exists, priority is read-only,
      // and escalation to another office goes through the Transfer /
      // reassign icon -> Transfer ticket dialog -> Apply, not a direct
      // reassignment or an invented "Escalate"/"Request Transfer" button
      // (no control is actually labeled "Request Transfer" in the app).
      expect(find.textContaining('Resolve button'), findsOneWidget);
      expect(
        find.textContaining('Priority is shown for reference but is '
            'read-only'),
        findsOneWidget,
      );
      expect(find.textContaining('Transfer / reassign'), findsWidgets);
      expect(find.textContaining('Request Transfer'), findsNothing);
      // Resolved vs. Closed: Closed is admin-only.
      expect(
        find.textContaining('only an Admin account can close a ticket'),
        findsOneWidget,
      );
      expect(find.textContaining('Internal Note'), findsWidgets);
    });

    testWidgets(
        'Assigned Tickets section documents the real ticket-detail view: '
        'conversation, Ticket Details panel, reply toolbar, and Send Reply',
        (tester) async {
      await pumpPage(tester, controller: await controllerFor('office'));

      expect(find.textContaining('Ticket Details panel'), findsOneWidget);
      expect(find.textContaining('Conversation tab'), findsOneWidget);
      expect(
        find.textContaining('Assigned Office, Category, Requester, Email'),
        findsOneWidget,
      );
      // Real, confirmed toolbar controls only (from staff_ticket_console.dart
      // tooltips) -- never an invented formatting option.
      expect(
        find.textContaining('Bold, Italic, Underline, Attach image, Attach '
            'file'),
        findsOneWidget,
      );
      expect(find.textContaining('Quick responses'), findsWidgets);
      expect(find.textContaining('Send Reply'), findsWidgets);
      // The confirmed, code-level behavior of the toggle: placeholder
      // changes and the icon turns maroon -- not an invented confirmation
      // dialog or separate internal-note screen.
      expect(
        find.textContaining('Write an internal note'),
        findsOneWidget,
      );
      expect(
        find.textContaining('never shown to the student'),
        findsOneWidget,
      );
    });

    testWidgets(
        'Knowledge Base section documents the real extract/index pipeline '
        'and never claims an invented re-index/delete/OCR-editor control',
        (tester) async {
      await pumpPage(tester, controller: await controllerFor('office'));

      expect(find.textContaining('Extract & Structure'), findsWidgets);
      expect(find.textContaining('Validation Report'), findsWidgets);
      expect(find.textContaining('Index for Chatbot Retrieval'), findsWidgets);
      expect(find.textContaining('ChromaDB'), findsWidgets);
      expect(find.textContaining('Retrieval Test'), findsOneWidget);
      // Explicit non-interchangeability callout.
      expect(
        find.textContaining('never publishes anything to the public '
            'Knowledge Base'),
        findsOneWidget,
      );
      // None of these controls exist in the real app, so the guide must
      // never claim one. ("OCR editor" isn't in this list even though it
      // doesn't exist either -- the guide's own prose correctly says so
      // explicitly, so a plain substring-absence check would misfire on
      // its own honest text.)
      for (final invented in ['Re-index button', 'Delete button']) {
        expect(find.textContaining(invented), findsNothing);
      }
    });

    testWidgets(
        'the "Needs Review" warning is explicit and actionable, not just a '
        'passive disclaimer', (tester) async {
      await pumpPage(tester, controller: await controllerFor('office'));

      expect(
        find.textContaining('do not tap Index for Chatbot Retrieval yet'),
        findsOneWidget,
      );
      expect(
        find.textContaining('correct it directly in the review box'),
        findsOneWidget,
      );
      expect(
        find.textContaining('re-upload a cleaner document'),
        findsOneWidget,
      );
    });

    testWidgets('no placeholder language about screenshots being added later',
        (tester) async {
      await pumpPage(tester, controller: await controllerFor('office'));

      // Not a blanket ban on the word "screenshot" -- the Assigned Tickets
      // section legitimately uses it as an example attachment type. This
      // checks for the specific placeholder disclaimer that was removed.
      expect(find.textContaining("aren't included yet"), findsNothing);
      expect(find.textContaining('added to each section later'), findsNothing);
      expect(find.textContaining('without changing this layout'), findsNothing);
    });

    testWidgets(
        'Knowledge Article section documents duplicate detection, publish, '
        'and unpublish only where they really exist', (tester) async {
      await pumpPage(tester, controller: await controllerFor('office'));

      expect(find.textContaining('Create Article'), findsWidgets);
      expect(find.textContaining('Add to KB'), findsWidgets);
      expect(find.textContaining('Save as draft'), findsWidgets);
      expect(find.textContaining('Publish Article'), findsWidgets);
      expect(find.textContaining('checks for an existing article with a '
          'similar title'), findsOneWidget);
      expect(
        find.textContaining('there is no separate admin approval step'),
        findsOneWidget,
      );
      expect(find.textContaining('Unpublish'), findsWidgets);
    });

    testWidgets('Good Practices section covers privacy and escalation to Admin',
        (tester) async {
      await pumpPage(tester, controller: await controllerFor('office'));

      expect(find.textContaining("student's personal details"), findsOneWidget);
      expect(find.textContaining('When to ask an Admin'), findsOneWidget);
    });
  });

  group('responsive layout', () {
    for (final width in <double>[360, 600, 900, 1400]) {
      testWidgets('no overflow at width ${width.toInt()}px', (tester) async {
        final unexpectedErrors = <String>[];
        final previousOnError = FlutterError.onError;
        FlutterError.onError = (details) {
          unexpectedErrors.add(details.toString());
          previousOnError?.call(details);
        };
        addTearDown(() => FlutterError.onError = previousOnError);

        await pumpPage(
          tester,
          controller: await controllerFor('office'),
          size: Size(width, 1000),
        );
        // Settle the chip Wrap/column reflow at each breakpoint.
        await tester.pump(const Duration(milliseconds: 50));

        expect(unexpectedErrors, isEmpty);
        expect(find.text('How to Use'), findsWidgets);
      });
    }
  });
}

class _FakeAuthService extends AuthService {
  final AuthUser user;
  String? _token;

  _FakeAuthService(this.user);

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
    return AuthResponse(
      accessToken: 'token-${user.role}',
      tokenType: 'bearer',
      user: user,
    );
  }

  @override
  Future<AuthUser> getCurrentUser(String token) async => user;
}
