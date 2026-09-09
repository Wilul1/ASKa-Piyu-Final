import 'package:flutter/material.dart';

import '../design_tokens.dart';
import 'admin_generate_articles_page.dart';
import 'admin_kb_workspace.dart';
class KbReviewAndPublishSection extends StatelessWidget {
  const KbReviewAndPublishSection({
    super.key,
    required this.knowledgeUnits,
    required this.fileName,
    required this.documentType,
    this.focusArticleId,
    this.onLibraryRefresh,
  });

  final List<Map<String, dynamic>> knowledgeUnits;
  final String? fileName;
  final String? documentType;
  final String? focusArticleId;
  final VoidCallback? onLibraryRefresh;

  @override
  Widget build(BuildContext context) {
    final cleanType = formatDocumentTypeLabel(documentType);
    final sessionContext = KbSessionDisplayContext(
      fileName: fileName,
      documentType: cleanType,
      knowledgeUnitCount: knowledgeUnits.length,
    );

    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(18),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: DesignTokens.border),
        boxShadow: DesignTokens.softShadow(0.04),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          const Text(
            'Review & Publish',
            style: TextStyle(
              fontSize: 22,
              fontWeight: FontWeight.w800,
              color: DesignTokens.ink,
            ),
          ),
          const SizedBox(height: 6),
          const Text(
            'Review extracted units, then generate student-facing article previews.',
            style: TextStyle(
              fontSize: 14,
              height: 1.45,
              color: DesignTokens.muted,
            ),
          ),
          const SizedBox(height: 18),
          KbKnowledgeUnitsReviewPanel(
            knowledgeUnits: knowledgeUnits,
            fileName: fileName,
            borderless: true,
          ),
          const SizedBox(height: 20),
          const Divider(height: 1),
          const SizedBox(height: 16),
          const Text(
            'Step 2 — Generate article previews',
            style: TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w800,
              color: DesignTokens.ink,
            ),
          ),
          const SizedBox(height: 12),
          AdminGenerateArticlesPage(
            embedded: true,
            embeddedCompact: true,
            showArticleLibrary: false,
            liveSessionContext: sessionContext,
            focusArticleId: focusArticleId,
            onLibraryRefresh: onLibraryRefresh,
          ),
        ],
      ),
    );
  }
}
