import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:aska_piyu/auth/auth_state.dart';
import 'package:aska_piyu/models/auth_models.dart';
import 'package:aska_piyu/screens/admin_kb_workspace.dart';
import 'package:aska_piyu/screens/admin_panel_page.dart';
import 'package:aska_piyu/services/auth_service.dart';
import 'package:aska_piyu/services/file_pick.dart';
import 'package:aska_piyu/services/kb_workspace_session.dart';
import 'package:aska_piyu/widgets/admin_action_buttons.dart';

/// Covers the zero-cost digital (selectable-text) PDF ingestion workflow:
/// POST /admin/knowledge-base/ingest-digital + GET
/// /admin/knowledge-base/jobs/{id} polling. This is a separate pipeline from
/// the existing extract/structure/ingest workflow and must not disturb it.
void main() {
  group('KbWorkspaceSession digital job state machine', () {
    test('starts in the ready state with no job', () {
      final session = KbWorkspaceSession();
      expect(session.digitalJobStatus, 'ready');
      expect(session.digitalJobId, isNull);
      expect(session.digitalIsBusy, isFalse);
      expect(session.digitalIsTerminal, isFalse);
    });

    test('setDigitalSelectedFile resets any previous job to ready', () {
      final session = KbWorkspaceSession();
      session.applyDigitalJobStatus({
        'status': 'published',
        'chunks_indexed': 12,
        'document_id': 'doc-1',
      });
      expect(session.digitalJobStatus, 'published');

      session.digitalJobId = 'job-1'; // simulate a completed upload
      session.setDigitalSelectedFile(
        PickedAppFile(name: 'handbook.pdf', bytes: Uint8ListFixture.pdf),
      );

      expect(session.digitalJobStatus, 'ready');
      expect(session.digitalJobId, isNull);
      expect(session.digitalChunksIndexed, isNull);
      expect(session.digitalDocumentId, isNull);
      expect(session.digitalSelectedFileName, 'handbook.pdf');
    });

    test('resetDigitalJob clears file selection and job fields', () {
      final session = KbWorkspaceSession();
      session.setDigitalSelectedFile(
        PickedAppFile(name: 'handbook.pdf', bytes: Uint8ListFixture.pdf),
      );
      session.applyDigitalJobStatus({'status': 'failed', 'error_message': 'boom'});

      session.resetDigitalJob();

      expect(session.digitalSelectedFile, isNull);
      expect(session.digitalSelectedFileName, isNull);
      expect(session.digitalJobStatus, 'ready');
      expect(session.digitalErrorMessage, isNull);
    });

    test('clear() also resets the digital job (e.g. on logout)', () {
      final session = KbWorkspaceSession();
      session.setDigitalSelectedFile(
        PickedAppFile(name: 'handbook.pdf', bytes: Uint8ListFixture.pdf),
      );
      session.applyDigitalJobStatus({'status': 'processing'});

      session.clear();

      expect(session.digitalJobStatus, 'ready');
      expect(session.digitalSelectedFile, isNull);
    });

    test('digitalIsBusy is true only for active (non-terminal, non-ready) statuses', () {
      final session = KbWorkspaceSession();
      for (final status in ['uploading', 'queued', 'processing']) {
        session.applyDigitalJobStatus({'status': status});
        expect(session.digitalIsBusy, isTrue, reason: status);
      }
      for (final status in [
        'ready',
        'published',
        'failed',
        'ocr_required',
        'needs_reconciliation',
      ]) {
        session.applyDigitalJobStatus({'status': status});
        expect(session.digitalIsBusy, isFalse, reason: status);
      }
    });

    test('digitalIsTerminal matches exactly the four backend terminal statuses', () {
      final session = KbWorkspaceSession();
      for (final status in [
        'published',
        'failed',
        'ocr_required',
        'needs_reconciliation',
      ]) {
        session.applyDigitalJobStatus({'status': status});
        expect(session.digitalIsTerminal, isTrue, reason: status);
      }
      for (final status in ['ready', 'uploading', 'queued', 'processing']) {
        session.applyDigitalJobStatus({'status': status});
        expect(session.digitalIsTerminal, isFalse, reason: status);
      }
    });
  });

  group('applyDigitalJobStatus parses the real IngestionJobStatusResponse schema', () {
    test('published job maps all fields', () {
      final session = KbWorkspaceSession();
      session.applyDigitalJobStatus({
        'job_id': 'job-123',
        'source_filename': 'handbook.pdf',
        'status': 'published',
        'status_detail': null,
        'page_count': 42,
        'document_id': 'doc-new',
        'replaced_document_id': 'doc-old',
        'chunks_indexed': 87,
        'error_message': null,
        'created_at': '2026-10-02T00:00:00',
        'updated_at': '2026-10-02T00:05:00',
      });

      expect(session.digitalJobStatus, 'published');
      expect(session.digitalPageCount, 42);
      expect(session.digitalChunksIndexed, 87);
      expect(session.digitalDocumentId, 'doc-new');
      expect(session.digitalReplacedDocumentId, 'doc-old');
      expect(session.digitalErrorMessage, isNull);
    });

    test('processing job surfaces status_detail for the progress label', () {
      final session = KbWorkspaceSession();
      session.applyDigitalJobStatus({
        'status': 'processing',
        'status_detail': 'Embedding and publishing 40 chunks...',
      });
      expect(session.digitalJobStatus, 'processing');
      expect(session.digitalStatusDetail, 'Embedding and publishing 40 chunks...');
    });

    test('failed job sanitizes a multi-line error to its first line', () {
      final session = KbWorkspaceSession();
      session.applyDigitalJobStatus({
        'status': 'failed',
        'error_message':
            'Adding the new version failed: Hugging Face embedding request failed with HTTP 401. in add.\nTraceback (most recent call last):\n  File "digital_ingestion.py", line 142',
      });
      expect(session.digitalJobStatus, 'failed');
      expect(
        session.digitalErrorMessage,
        'Adding the new version failed: Hugging Face embedding request failed with HTTP 401. in add.',
      );
      expect(session.digitalErrorMessage, isNot(contains('Traceback')));
    });

    test('needs_reconciliation job keeps the admin-attention error message', () {
      final session = KbWorkspaceSession();
      session.applyDigitalJobStatus({
        'status': 'needs_reconciliation',
        'error_message':
            'New version published but cleanup of the old version may be incomplete: delete failed.',
      });
      expect(session.digitalJobStatus, 'needs_reconciliation');
      expect(session.digitalErrorMessage, contains('cleanup of the old version'));
    });

    test('ocr_required job carries no chunk/document fields', () {
      final session = KbWorkspaceSession();
      session.applyDigitalJobStatus({
        'status': 'ocr_required',
        'status_detail':
            'This PDF does not contain enough selectable digital text and requires OCR processing.',
      });
      expect(session.digitalJobStatus, 'ocr_required');
      expect(session.digitalChunksIndexed, isNull);
      expect(session.digitalDocumentId, isNull);
    });
  });

  group('sanitizeDigitalIngestionError', () {
    test('passes short single-line messages through unchanged', () {
      expect(
        sanitizeDigitalIngestionError('Another ingestion job is already in progress.'),
        'Another ingestion job is already in progress.',
      );
    });

    test('truncates very long messages to 240 chars with an ellipsis', () {
      final long = 'x' * 500;
      final result = sanitizeDigitalIngestionError(long);
      expect(result.length, 241); // 240 chars + the ellipsis character
      expect(result.endsWith('…'), isTrue);
    });

    test('falls back to a generic message for empty input', () {
      expect(sanitizeDigitalIngestionError('   '),
          'An unexpected error occurred. Please try again.');
    });
  });

  group('AdminKbWorkspace digital ingestion UI states', () {
    Widget wrap(Widget child, {Size size = const Size(1200, 1000)}) {
      return MediaQuery(
        data: MediaQueryData(size: size),
        child: Directionality(
          textDirection: TextDirection.ltr,
          child: Material(child: SingleChildScrollView(child: child)),
        ),
      );
    }

    AdminKbWorkspace buildWorkspace({
      String digitalJobStatus = 'ready',
      String? digitalFileName,
      String? digitalStatusDetail,
      int? digitalChunksIndexed,
      String? digitalErrorMessage,
      bool digitalDuplicateOfExistingJob = false,
      bool digitalIsBusy = false,
      bool digitalIsPolling = false,
      bool digitalHasJob = false,
    }) {
      return AdminKbWorkspace(
        fileName: null,
        fileSizeBytes: null,
        isBusy: false,
        status: '',
        pipelineStages: const [],
        knowledgeUnits: const [],
        validationReport: null,
        kbStatistics: null,
        reviewText: '',
        rawOcrText: null,
        documentType: null,
        classificationReason: null,
        publishedCount: null,
        draftCount: null,
        candidateHintCount: null,
        selectedOutlineIndex: 0,
        onPickFile: () {},
        onExtract: () {},
        onIngest: () {},
        onSelectOutline: (_) {},
        digitalFileName: digitalFileName,
        digitalFileSizeBytes: null,
        digitalJobStatus: digitalJobStatus,
        digitalStatusDetail: digitalStatusDetail,
        digitalPageCount: null,
        digitalChunksIndexed: digitalChunksIndexed,
        digitalErrorMessage: digitalErrorMessage,
        digitalDuplicateOfExistingJob: digitalDuplicateOfExistingJob,
        digitalIsBusy: digitalIsBusy,
        digitalIsPolling: digitalIsPolling,
        digitalHasJob: digitalHasJob,
        onPickDigitalFile: () {},
        onUploadDigital: () {},
        onResetDigitalJob: () {},
        onCheckDigitalJobNow: () {},
      );
    }

    testWidgets('ready state shows the picker and a disabled upload button',
        (tester) async {
      await tester.pumpWidget(wrap(buildWorkspace()));
      expect(find.text('Choose PDF'), findsOneWidget);
      expect(find.text('Upload & Process'), findsOneWidget);
      expect(find.text('Ready'), findsOneWidget);

      final button = tester.widget<AdminPrimaryButton>(
        find.widgetWithText(AdminPrimaryButton, 'Upload & Process'),
      );
      expect(button.onPressed, isNull); // no file chosen yet
    });

    testWidgets('a selected file enables the upload button', (tester) async {
      await tester.pumpWidget(
          wrap(buildWorkspace(digitalFileName: 'handbook.pdf')));
      final button = tester.widget<AdminPrimaryButton>(
        find.widgetWithText(AdminPrimaryButton, 'Upload & Process'),
      );
      expect(button.onPressed, isNotNull);
    });

    testWidgets(
        'uploading/queued/processing disable the upload button (duplicate-submission guard)',
        (tester) async {
      for (final status in ['uploading', 'queued', 'processing']) {
        await tester.pumpWidget(wrap(buildWorkspace(
          digitalFileName: 'handbook.pdf',
          digitalJobStatus: status,
          digitalIsBusy: true,
        )));
        final button = tester.widget<AdminPrimaryButton>(
          find.widgetWithText(AdminPrimaryButton, 'Upload & Process'),
        );
        expect(button.onPressed, isNull, reason: status);
      }
    });

    testWidgets('published state shows filename, chunk count, and a reset action',
        (tester) async {
      await tester.pumpWidget(wrap(buildWorkspace(
        digitalFileName: 'handbook.pdf',
        digitalJobStatus: 'published',
        digitalChunksIndexed: 87,
      )));
      expect(find.textContaining('87 chunks indexed'), findsOneWidget);
      expect(find.text('Process Another PDF'), findsOneWidget);
    });

    testWidgets('ocr_required explains the limitation and never offers a retry',
        (tester) async {
      await tester.pumpWidget(wrap(buildWorkspace(
        digitalFileName: 'scanned.pdf',
        digitalJobStatus: 'ocr_required',
      )));
      expect(
        find.textContaining(
            'This PDF does not contain enough selectable digital text and requires OCR processing.'),
        findsOneWidget,
      );
      expect(find.text('Choose a Different File'), findsOneWidget);
      expect(find.text('Retry'), findsNothing);
    });

    testWidgets('failed state shows the sanitized error and a Try Again action',
        (tester) async {
      await tester.pumpWidget(wrap(buildWorkspace(
        digitalFileName: 'handbook.pdf',
        digitalJobStatus: 'failed',
        digitalErrorMessage: 'Adding the new version failed: HTTP 401.',
      )));
      expect(
          find.text('Adding the new version failed: HTTP 401.'), findsOneWidget);
      expect(find.text('Try Again'), findsOneWidget);
    });

    testWidgets(
        'needs_reconciliation warns that admin attention is required and offers no auto-retry',
        (tester) async {
      await tester.pumpWidget(wrap(buildWorkspace(
        digitalFileName: 'handbook.pdf',
        digitalJobStatus: 'needs_reconciliation',
        digitalErrorMessage: 'Cleanup of the old version may be incomplete.',
      )));
      expect(find.textContaining('Administrator Attention Required'),
          findsOneWidget);
      expect(find.text('Dismiss'), findsOneWidget);
      expect(find.text('Try Again'), findsNothing);
      expect(find.text('Retry'), findsNothing);
    });

    testWidgets('duplicate-of-existing-job note is shown when flagged',
        (tester) async {
      await tester.pumpWidget(wrap(buildWorkspace(
        digitalFileName: 'handbook.pdf',
        digitalJobStatus: 'published',
        digitalDuplicateOfExistingJob: true,
      )));
      expect(
        find.textContaining('This file was already submitted before'),
        findsOneWidget,
      );
    });

    testWidgets(
        'a stalled (non-terminal, non-polling) job offers a manual Check Status Now action',
        (tester) async {
      await tester.pumpWidget(wrap(buildWorkspace(
        digitalFileName: 'handbook.pdf',
        digitalJobStatus: 'processing',
        digitalIsBusy: false,
        digitalIsPolling: false,
        digitalHasJob: true,
        digitalStatusDetail:
            'Lost contact with the server while checking status. Use "Check status now" below.',
      )));
      expect(find.text('Check Status Now'), findsOneWidget);
    });

    testWidgets('renders without overflow at a narrow mobile width',
        (tester) async {
      await tester.pumpWidget(wrap(
        buildWorkspace(digitalFileName: 'handbook.pdf', digitalJobStatus: 'processing'),
        size: const Size(360, 800),
      ));
      await tester.pump();
      expect(tester.takeException(), isNull);
    });

    testWidgets('renders without overflow at a desktop width', (tester) async {
      await tester.pumpWidget(wrap(
        buildWorkspace(digitalFileName: 'handbook.pdf', digitalJobStatus: 'published'),
        size: const Size(1440, 900),
      ));
      await tester.pump();
      expect(tester.takeException(), isNull);
    });
  });

  group('Admin Knowledge Base page (real composition)', () {
    // Renders the actual route an admin reaches via the "Knowledge Base"
    // sidebar item (AdminPanelPage, wrapped the same way main.dart wraps
    // every page: AuthScope > KbWorkspaceScope > MaterialApp), not just
    // AdminKbWorkspace/_DigitalIngestionCard in isolation. This is the
    // regression test for "the card doesn't show up on the live page even
    // though the strings are in the deployed bundle" -- it proves the
    // widget composition itself is correct.
    testWidgets(
        'Digital PDF Processing (Zero-Cost) is visible on the real Admin Knowledge Base page',
        (tester) async {
      await tester.binding.setSurfaceSize(const Size(1400, 1000));
      addTearDown(() => tester.binding.setSurfaceSize(null));

      final controller = AuthController(service: _TestAuthService(_testAdminUser()));
      await controller.login(
        const LoginRequest(email: 'admin@example.edu', password: 'password'),
      );

      final session = KbWorkspaceSession();
      addTearDown(session.dispose);

      await tester.pumpWidget(
        AuthScope(
          controller: controller,
          child: KbWorkspaceScope(
            session: session,
            child: const MaterialApp(home: AdminPanelPage()),
          ),
        ),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 50));

      // Sanity check: the existing extract/ingest workflow is still there.
      expect(find.text('Extract & Index'), findsOneWidget);
      expect(find.text('Active Document'), findsOneWidget);

      // The actual regression assertion.
      expect(find.text('Digital PDF Processing (Zero-Cost)'), findsOneWidget);
      expect(find.text('Choose PDF'), findsOneWidget);
      expect(find.text('Upload & Process'), findsOneWidget);
    });
  });
}

/// Small fixed PDF-ish byte fixture so PickedAppFile can be constructed
/// without a real file picker in these widget/unit tests.
class Uint8ListFixture {
  static final Uint8List pdf = Uint8List.fromList(List<int>.generate(16, (i) => i));
}

AuthUser _testAdminUser() {
  return const AuthUser(
    id: 'admin-1',
    email: 'admin@example.edu',
    fullName: 'Campus Admin',
    role: 'admin',
    officeId: null,
    officeName: null,
    emailVerified: true,
    createdAt: null,
    updatedAt: null,
  );
}

class _TestAuthService extends AuthService {
  final AuthUser user;
  String? _token;

  _TestAuthService(this.user);

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
    _token = 'token';
    return AuthResponse(
      accessToken: 'token',
      tokenType: 'bearer',
      user: user,
    );
  }

  @override
  Future<AuthUser> getCurrentUser(String token) async => user;
}
