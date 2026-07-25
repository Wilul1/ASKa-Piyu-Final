import 'dart:html' as html;
import 'dart:typed_data';
import 'dart:ui_web' as ui_web;

import 'package:flutter/material.dart';

Future<void> openPdfExternally(Uint8List bytes) async {
  final blob = html.Blob([bytes], 'application/pdf');
  final url = html.Url.createObjectUrlFromBlob(blob);
  html.window.open(url, '_blank');
}

class SourcePdfEmbed extends StatefulWidget {
  const SourcePdfEmbed({super.key, required this.bytes});

  final Uint8List bytes;

  @override
  State<SourcePdfEmbed> createState() => _SourcePdfEmbedState();
}

class _SourcePdfEmbedState extends State<SourcePdfEmbed> {
  late final String _viewType;
  late final String _blobUrl;

  @override
  void initState() {
    super.initState();
    final blob = html.Blob([widget.bytes], 'application/pdf');
    _blobUrl = html.Url.createObjectUrlFromBlob(blob);
    _viewType = 'aska-source-pdf-${DateTime.now().microsecondsSinceEpoch}';
    ui_web.platformViewRegistry.registerViewFactory(_viewType, (int viewId) {
      final element = html.IFrameElement()
        ..src = _blobUrl
        ..style.border = 'none'
        ..style.width = '100%'
        ..style.height = '100%'
        ..allowFullscreen = true;
      return element;
    });
  }

  @override
  void dispose() {
    html.Url.revokeObjectUrl(_blobUrl);
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return HtmlElementView(viewType: _viewType);
  }
}
