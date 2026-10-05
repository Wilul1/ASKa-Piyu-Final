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

  group('AdminKbWorkspace no longer renders the Digital PDF Processing card',
      () {
    // The lightweight/cloud-safe pipeline (PyMuPDF + remote AWS OCR
    // fallback + publish_new_version) is now reached through the SAME
    // Extract & Structure / Index for Chatbot Retrieval buttons the legacy
    // local pipeline already used -- see
    // backend/app/services/admin/digital_ingestion.py
    // (build_lightweight_preview / build_lightweight_publish) and
    // backend/app/routes/admin/knowledge_base.py's ingestion_available()
    // branch. The separate "Digital PDF Processing (Zero-Cost)" card is
    // removed from the rendered tree; its digital*/onXDigital fields stay
    // on AdminKbWorkspace's constructor (unused by build()) only so this
    // widget's public API doesn't need to change everywhere it's
    // constructed. The backend endpoints it used to drive
    // (POST /ingest-digital, GET /jobs/{id}, process_ingestion_job) are
    // intentionally untouched -- see the KbWorkspaceSession tests above.
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
        digitalStatusDetail: null,
        digitalPageCount: null,
        digitalChunksIndexed: null,
        digitalErrorMessage: null,
        digitalDuplicateOfExistingJob: false,
        digitalIsBusy: false,
        digitalIsPolling: false,
        digitalHasJob: false,
        onPickDigitalFile: () {},
        onUploadDigital: () {},
        onResetDigitalJob: () {},
        onCheckDigitalJobNow: () {},
      );
    }

    testWidgets(
        'the Digital PDF Processing card and its controls are not rendered',
        (tester) async {
      await tester.pumpWidget(wrap(buildWorkspace(
        digitalFileName: 'handbook.pdf',
        digitalJobStatus: 'published',
      )));
      expect(find.text('Digital PDF Processing (Zero-Cost)'), findsNothing);
      expect(find.text('Choose PDF'), findsNothing);
      expect(find.text('Upload & Process'), findsNothing);
    });

    testWidgets(
        'the existing Extract & Structure / Index for Chatbot Retrieval buttons still render',
        (tester) async {
      await tester.pumpWidget(wrap(buildWorkspace()));
      expect(find.text('Extract & Structure'), findsOneWidget);
      expect(find.text('Index for Chatbot Retrieval'), findsOneWidget);
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
    // AdminKbWorkspace in isolation. Extract & Index is now the one and
    // only document-processing workflow visible here -- the separate
    // "Digital PDF Processing (Zero-Cost)" card must not appear on the
    // live page composition.
    testWidgets(
        'Digital PDF Processing (Zero-Cost) is no longer visible on the real Admin Knowledge Base page',
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

      // Sanity check: the existing extract/ingest workflow is still there
      // and still wired to its buttons (requirement: these remain the
      // primary production document-processing workflow).
      expect(find.text('Extract & Index'), findsOneWidget);
      expect(find.text('Active Document'), findsOneWidget);
      expect(find.text('Extract & Structure'), findsOneWidget);
      expect(find.text('Index for Chatbot Retrieval'), findsOneWidget);

      // The actual regression assertion: the separate zero-cost digital
      // card is gone from the real page composition, not just from the
      // isolated widget tests above.
      expect(find.text('Digital PDF Processing (Zero-Cost)'), findsNothing);
      expect(find.text('Choose PDF'), findsNothing);
      expect(find.text('Upload & Process'), findsNothing);
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
