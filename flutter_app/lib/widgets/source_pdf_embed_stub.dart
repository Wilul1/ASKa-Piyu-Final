import 'dart:io';
import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:open_filex/open_filex.dart';
import 'package:path_provider/path_provider.dart';

import '../design_tokens.dart';

Future<void> openPdfExternally(Uint8List bytes) async {
  final dir = await getTemporaryDirectory();
  final file = File(
    '${dir.path}/aska_source_${DateTime.now().millisecondsSinceEpoch}.pdf',
  );
  await file.writeAsBytes(bytes, flush: true);
  await OpenFilex.open(file.path);
}

class SourcePdfEmbed extends StatelessWidget {
  const SourcePdfEmbed({super.key, required this.bytes});

  final Uint8List bytes;

  @override
  Widget build(BuildContext context) {
    return Center(
      child: Padding(
        padding: const EdgeInsets.all(24),
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.picture_as_pdf_rounded,
                size: 48, color: DesignTokens.maroon),
            const SizedBox(height: 12),
            const Text(
              'PDF preview opens in your device viewer on mobile/desktop.',
              textAlign: TextAlign.center,
              style: TextStyle(color: DesignTokens.muted),
            ),
            const SizedBox(height: 16),
            FilledButton.icon(
              onPressed: () => openPdfExternally(bytes),
              icon: const Icon(Icons.open_in_new_rounded),
              label: const Text('Open PDF'),
            ),
          ],
        ),
      ),
    );
  }
}
