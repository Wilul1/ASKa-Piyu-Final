import 'dart:async';
import 'dart:convert';

import 'package:flutter/widgets.dart';
import 'package:http/http.dart' as http;

import '../app_config.dart';
import '../services/api_client.dart';
import '../services/extraction_preview_store.dart';
import '../services/file_pick.dart';

String sanitizePipelineStageLabel(String label) {
  final normalized = label.trim().toLowerCase();
  if (normalized == 'llm structuring' ||
      normalized.contains('llm structur')) {
    return 'Structuring extracted content';
  }
  return label;
}

/// Survives Knowledge Base page disposal so extract/ingest keep running when
/// the admin navigates away and comes back.
class KbWorkspaceSession extends ChangeNotifier {
  PickedAppFile? selectedFile;
  String? selectedFileName;
  String status = 'Choose a document to begin.';
  String reviewText = '';
  String? rawOcrText;
  List<KbPipelineStage> pipelineStages = KbPipelineStage.defaults();
  Map<String, dynamic>? validationReport;
  Map<String, dynamic>? kbStatistics;
  List<Map<String, dynamic>> knowledgeUnits = [];
  List<Map<String, dynamic>> chunkPreview = [];
  Map<String, dynamic>? extractionPreview;
  String? extractedDocumentType;
  String? classificationReason;
  int selectedOutlineIndex = 0;
  int? candidateHintCount;
  bool isBusy = false;
  bool isExtracting = false;
  bool isIndexing = false;

  Timer? _progressTimer;
  int _progressStep = 0;
  int _operationToken = 0;

  void clear() {
    _progressTimer?.cancel();
    _progressTimer = null;
    _operationToken++;
    selectedFile = null;
    selectedFileName = null;
    status = 'Choose a document to begin.';
    reviewText = '';
    rawOcrText = null;
    pipelineStages = KbPipelineStage.defaults();
    validationReport = null;
    kbStatistics = null;
    knowledgeUnits = [];
    chunkPreview = [];
    extractionPreview = null;
    extractedDocumentType = null;
    classificationReason = null;
    selectedOutlineIndex = 0;
    candidateHintCount = null;
    isBusy = false;
    isExtracting = false;
    isIndexing = false;
    _progressStep = 0;
    notifyListeners();
  }

  void setStatusMessage(String value) {
    status = value;
    notifyListeners();
  }

  void setKbStatistics(Map<String, dynamic>? value) {
    kbStatistics = value;
    notifyListeners();
  }

  void setSelectedFile(PickedAppFile file) {
    selectedFile = file;
    selectedFileName = file.name;
    status = 'Ready to extract ${file.name}.';
    pipelineStages = KbPipelineStage.defaults();
    validationReport = null;
    knowledgeUnits = [];
    chunkPreview = [];
    rawOcrText = null;
    reviewText = '';
    extractionPreview = null;
    extractedDocumentType = null;
    classificationReason = null;
    candidateHintCount = null;
    selectedOutlineIndex = 0;
    notifyListeners();
  }

  void setSelectedOutlineIndex(int index) {
    selectedOutlineIndex = index;
    notifyListeners();
  }

  void setReviewText(String value) {
    if (reviewText == value) return;
    reviewText = value;
    notifyListeners();
  }

  void hydrateFromCachedPreview(Map<String, dynamic> cached) {
    if (isBusy) return;
    final previewRaw = cached['preview'];
    if (previewRaw is! Map) return;
    final preview = Map<String, dynamic>.from(previewRaw);
    extractionPreview = preview;
    knowledgeUnits = _readMapList(preview['knowledge_units']);
    selectedFileName =
        cached['source_filename']?.toString() ?? selectedFileName;
    extractedDocumentType =
        (cached['detected_document_type'] ?? cached['document_type'])
            ?.toString();
    classificationReason =
        (cached['detected_document_type'] ?? cached['classification_reason'])
            ?.toString();
    validationReport = _readMap(preview['validation_report']);
    kbStatistics = _readMap(preview['kb_statistics']);
    chunkPreview = _readMapList(preview['chunk_preview']);
    candidateHintCount = _asInt(cached['knowledge_units_count']) ??
        (knowledgeUnits.isEmpty ? null : knowledgeUnits.length);
    final review = preview['review_text'] ?? preview['extracted_text'];
    if (review is String && review.trim().isNotEmpty) {
      reviewText = review;
    }
    final cachedStatus = cached['status']?.toString();
    if (cachedStatus != null && cachedStatus.isNotEmpty) {
      status = cachedStatus;
    }
    notifyListeners();
  }

  Future<void> runExtract({
    required void Function(Map<String, String> headers) setAdminHeader,
    required String Function(String message) authError,
    required String Function(int? status, dynamic detail) requestError,
    required String Function(String value) cleanPreviewText,
    required String? Function(Object? value) formatDocumentTypeLabel,
    required String? Function(Object? value) formatClassificationReason,
  }) async {
    await _runDocumentJob(
      path: '/admin/knowledge-base/extract',
      includeTitle: false,
      busyLabel: 'Extracting, cleaning, and structuring the document...',
      progressMode: _ProgressMode.extract,
      setAdminHeader: setAdminHeader,
      authError: authError,
      requestError: requestError,
      onSuccess: (data) async {
        final extracted = data['review_text'] ?? data['extracted_text'];
        final rawText = data['raw_text'];
        final documentType = formatDocumentTypeLabel(
          data['detected_document_type'] ?? data['document_type'],
        );
        final reason = formatClassificationReason(
          data['detected_document_type'] ?? data['classification_reason'],
        );
        final units = _readMapList(data['knowledge_units']);
        final handoff = buildExtractionHandoffPackage(
          extractResponse: data,
          sourceFilename: selectedFileName ??
              data['source_filename']?.toString() ??
              '',
          status: 'Extraction preview is ready.',
          classificationReason: reason,
        );
        final preview = Map<String, dynamic>.from(handoff['preview'] as Map);
        final saved = await AppConfig.saveLastExtractionPreview(handoff);

        reviewText = extracted is String
            ? cleanPreviewText(extracted)
            : _prettyJson(data);
        rawOcrText =
            rawText is String && rawText.trim().isNotEmpty ? rawText : null;
        pipelineStages = _readPipelineStages(data['pipeline_stages']);
        validationReport = _readMap(data['validation_report']);
        kbStatistics = _readMap(data['kb_statistics']);
        knowledgeUnits = units;
        chunkPreview = _readMapList(data['chunk_preview']);
        extractionPreview = preview;
        extractedDocumentType = documentType;
        classificationReason = reason;
        selectedOutlineIndex = 0;
        candidateHintCount = units.isEmpty ? null : units.length;
        status = saved
            ? 'Extraction preview is ready. Ready to generate article previews below.'
            : 'Extraction preview is ready, but saving for Generate Articles failed (browser storage full). Try Reload after clearing site data, or re-extract a smaller document.';
      },
    );
  }

  Future<void> runIngest({
    required void Function(Map<String, String> headers) setAdminHeader,
    required String Function(String message) authError,
    required String Function(int? status, dynamic detail) requestError,
    required FutureOr<void> Function() onIndexed,
  }) async {
    await _runDocumentJob(
      path: '/admin/knowledge-base/ingest',
      includeTitle: true,
      busyLabel: 'Indexing knowledge units for chatbot retrieval...',
      progressMode: _ProgressMode.ingest,
      setAdminHeader: setAdminHeader,
      authError: authError,
      requestError: requestError,
      onSuccess: (data) async {
        final chunks = data['chunks_indexed'];
        pipelineStages = _readPipelineStages(data['pipeline_stages']);
        validationReport = _readMap(data['validation_report']);
        kbStatistics = _readMap(data['kb_statistics']);
        knowledgeUnits = _readMapList(data['knowledge_units']);
        chunkPreview = _readMapList(data['chunk_preview']);
        status =
            'Knowledge units indexed for chatbot retrieval. Indexed ${chunks ?? 0} chunks.';
        await onIndexed();
      },
    );
  }

  Future<void> _runDocumentJob({
    required String path,
    required bool includeTitle,
    required String busyLabel,
    required _ProgressMode progressMode,
    required void Function(Map<String, String> headers) setAdminHeader,
    required String Function(String message) authError,
    required String Function(int? status, dynamic detail) requestError,
    required FutureOr<void> Function(Map<String, dynamic> data) onSuccess,
  }) async {
    final file = selectedFile;
    if (file == null) {
      status = 'Please choose a PDF or image first.';
      notifyListeners();
      return;
    }
    if (isBusy) {
      status = isExtracting
          ? 'Extraction is already running. Stay on this page or come back when it finishes.'
          : 'Indexing is already running. Stay on this page or come back when it finishes.';
      notifyListeners();
      return;
    }

    final token = ++_operationToken;
    isBusy = true;
    isExtracting = progressMode == _ProgressMode.extract;
    isIndexing = progressMode == _ProgressMode.ingest;
    status = busyLabel;
    _startOptimisticProgress(progressMode);
    notifyListeners();

    try {
      final fields = <String, String>{};
      if (includeTitle) {
        fields['title'] = file.name;
        fields['reviewed_text'] = reviewText.trim();
        final lowerName = file.name.toLowerCase();
        final detected = (extractedDocumentType ?? '').trim().toLowerCase();
        final normalizedName = lowerName.replaceAll(
          RegExp(r'[\u2010-\u2015\u2212\uFE58\uFE63\uFF0D]'),
          '-',
        );
        if (normalizedName.contains('charter') ||
            normalizedName.contains('-cc_') ||
            normalizedName.contains('_cc_') ||
            RegExp(r'(^|[^a-z0-9])cc[_-]').hasMatch(normalizedName) ||
            normalizedName.contains('citizen') ||
            detected.contains('charter') ||
            detected.contains('procedure') ||
            detected.contains('service')) {
          fields['document_type'] = 'citizen_charter';
        }
      }

      final headers = <String, String>{};
      setAdminHeader(headers);
      // Faculty manuals / large PDFs often exceed the default 60s HTTP timeout
      // during OCR + handbook structuring. Keep the UI waiting longer.
      final result = await ApiClient.multipart(
        method: 'POST',
        url: '${AppConfig.resolvedApiBase}$path',
        headers: headers,
        fields: fields.isEmpty ? null : fields,
        files: [
          http.MultipartFile.fromBytes(
            'file',
            file.bytes,
            filename: file.name,
          ),
        ],
        timeout: const Duration(minutes: 20),
      );

      if (token != _operationToken) return;

      final responseText = result.body;
      final decoded = result.json;
      final data = decoded is Map<String, dynamic>
          ? decoded
          : <String, dynamic>{'response': decoded};

      if (result.statusCode == 200) {
        await onSuccess(data);
      } else {
        status = requestError(result.statusCode, data['detail']);
        reviewText = responseText;
        _markProgressFailed();
      }
    } on StateError catch (error) {
      if (token != _operationToken) return;
      status = authError(error.message);
      reviewText = error.message;
      _markProgressFailed();
    } on TimeoutException {
      if (token != _operationToken) return;
      status =
          'Extraction timed out. Large PDFs can take a few minutes — please try again.';
      reviewText =
          'TimeoutException: document extract/index exceeded the client wait limit.';
      _markProgressFailed();
    } catch (error) {
      if (token != _operationToken) return;
      status = 'Could not reach the backend.';
      reviewText = error.toString();
      _markProgressFailed();
    } finally {
      if (token == _operationToken) {
        _progressTimer?.cancel();
        _progressTimer = null;
        isBusy = false;
        isExtracting = false;
        isIndexing = false;
        notifyListeners();
      }
    }
  }

  void _startOptimisticProgress(_ProgressMode mode) {
    _progressTimer?.cancel();
    _progressStep = 0;
    if (mode == _ProgressMode.extract) {
      pipelineStages = [
        const KbPipelineStage(
          label: 'OCR/PDF extraction',
          status: 'running',
          detail: 'Reading the document…',
        ),
        const KbPipelineStage(label: 'Automatic cleaning', status: 'waiting'),
        const KbPipelineStage(
            label: 'Structuring extracted content',
            status: 'waiting',
          ),
        const KbPipelineStage(label: 'Admin review/edit', status: 'waiting'),
        const KbPipelineStage(label: 'Index to ChromaDB', status: 'waiting'),
      ];
    } else {
      pipelineStages = [
        const KbPipelineStage(
          label: 'OCR/PDF extraction',
          status: 'done',
        ),
        const KbPipelineStage(label: 'Automatic cleaning', status: 'done'),
        const KbPipelineStage(
          label: 'Structuring extracted content',
          status: 'done',
        ),
        const KbPipelineStage(label: 'Admin review/edit', status: 'done'),
        const KbPipelineStage(
          label: 'Index to ChromaDB',
          status: 'running',
          detail: 'Writing chunks…',
        ),
      ];
      return;
    }

    // Advance extract stages on a gentle cadence so waiting feels active.
    _progressTimer = Timer.periodic(const Duration(seconds: 4), (_) {
      if (!isBusy || !isExtracting) {
        _progressTimer?.cancel();
        return;
      }
      _progressStep++;
      if (_progressStep == 1) {
        pipelineStages = [
          const KbPipelineStage(
            label: 'OCR/PDF extraction',
            status: 'done',
            detail: 'Text layer / OCR complete',
          ),
          const KbPipelineStage(
            label: 'Automatic cleaning',
            status: 'running',
            detail: 'Normalizing text…',
          ),
          const KbPipelineStage(
            label: 'Structuring extracted content',
            status: 'waiting',
          ),
          const KbPipelineStage(label: 'Admin review/edit', status: 'waiting'),
          const KbPipelineStage(label: 'Index to ChromaDB', status: 'waiting'),
        ];
        status = 'Cleaning extracted text…';
      } else if (_progressStep == 2) {
        pipelineStages = [
          const KbPipelineStage(label: 'OCR/PDF extraction', status: 'done'),
          const KbPipelineStage(label: 'Automatic cleaning', status: 'done'),
          const KbPipelineStage(
            label: 'Structuring extracted content',
            status: 'running',
            detail: 'Building knowledge units…',
          ),
          const KbPipelineStage(label: 'Admin review/edit', status: 'waiting'),
          const KbPipelineStage(label: 'Index to ChromaDB', status: 'waiting'),
        ];
        status = 'Structuring knowledge units…';
      } else {
        // Stay on structuring until the server responds.
        status =
            'Still structuring — large documents can take a few minutes. You can leave this page and come back.';
      }
      notifyListeners();
    });
  }

  void _markProgressFailed() {
    pipelineStages = pipelineStages
        .map(
          (stage) => stage.status == 'running'
              ? KbPipelineStage(
                  label: stage.label,
                  status: 'error',
                  detail: 'Stopped',
                )
              : stage,
        )
        .toList();
  }

  static List<KbPipelineStage> _readPipelineStages(dynamic value) {
    if (value is! List) {
      return KbPipelineStage.defaults();
    }
    return value.map((item) {
      if (item is! Map) {
        return const KbPipelineStage(label: 'Unknown step', status: 'waiting');
      }
      return KbPipelineStage(
        label: sanitizePipelineStageLabel((item['label'] ?? '').toString()),
        status: (item['status'] ?? 'waiting').toString(),
        detail: item['detail']?.toString(),
      );
    }).toList();
  }

  static Map<String, dynamic>? _readMap(dynamic value) {
    if (value is Map<String, dynamic>) return value;
    if (value is Map) return Map<String, dynamic>.from(value);
    return null;
  }

  static List<Map<String, dynamic>> _readMapList(dynamic value) {
    if (value is! List) return [];
    return value
        .whereType<Map>()
        .map((item) => Map<String, dynamic>.from(item))
        .toList();
  }

  static int? _asInt(Object? value) {
    if (value is int) return value;
    return int.tryParse((value ?? '').toString());
  }

  static String _prettyJson(Map<String, dynamic> data) {
    return const JsonEncoder.withIndent('  ').convert(data);
  }

  @override
  void dispose() {
    _progressTimer?.cancel();
    super.dispose();
  }
}

enum _ProgressMode { extract, ingest }

class KbPipelineStage {
  final String label;
  final String status;
  final String? detail;

  const KbPipelineStage({
    required this.label,
    required this.status,
    this.detail,
  });

  static List<KbPipelineStage> defaults() => const [
        KbPipelineStage(label: 'OCR/PDF extraction', status: 'waiting'),
        KbPipelineStage(label: 'Automatic cleaning', status: 'waiting'),
        KbPipelineStage(
          label: 'Structuring extracted content',
          status: 'waiting',
        ),
        KbPipelineStage(label: 'Admin review/edit', status: 'waiting'),
        KbPipelineStage(label: 'Index to ChromaDB', status: 'waiting'),
      ];
}

class KbWorkspaceScope extends InheritedNotifier<KbWorkspaceSession> {
  const KbWorkspaceScope({
    super.key,
    required KbWorkspaceSession session,
    required super.child,
  }) : super(notifier: session);

  static KbWorkspaceSession of(BuildContext context) {
    final scope =
        context.dependOnInheritedWidgetOfExactType<KbWorkspaceScope>();
    assert(scope != null, 'KbWorkspaceScope was not found in the widget tree.');
    return scope!.notifier!;
  }

  static KbWorkspaceSession? maybeOf(BuildContext context) {
    return context
        .dependOnInheritedWidgetOfExactType<KbWorkspaceScope>()
        ?.notifier;
  }
}
