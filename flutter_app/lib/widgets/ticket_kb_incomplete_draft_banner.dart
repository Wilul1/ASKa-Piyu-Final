import 'package:flutter/material.dart';

import '../design_tokens.dart';
import '../services/kb_compose_helpers.dart';

/// Prominent warning for ticket-derived drafts that are not ready to publish.
class TicketKbIncompleteDraftBanner extends StatelessWidget {
  const TicketKbIncompleteDraftBanner({
    super.key,
    this.generationNotes,
    this.show = true,
  });

  final String? generationNotes;
  final bool show;

  @override
  Widget build(BuildContext context) {
    if (!show) return const SizedBox.shrink();
    final notes = formatTicketKbGenerationNotes(generationNotes);
    return Container(
      key: const Key('ticket-kb-incomplete-banner'),
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
      decoration: BoxDecoration(
        color: const Color(0xFFFFF7ED),
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: const Color(0xFFFDBA74)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Icon(
                Icons.warning_amber_rounded,
                color: Color(0xFFC2410C),
                size: 22,
              ),
              SizedBox(width: 10),
              Expanded(
                child: Text(
                  'Needs staff review before publishing',
                  style: TextStyle(
                    color: Color(0xFF9A3412),
                    fontWeight: FontWeight.w800,
                    fontSize: 14,
                    height: 1.3,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 8),
          const Text(
            'The original ticket conversation may not have enough reusable '
            'detail for a public Knowledge Base article. Review and edit the '
            'draft below. Publish remains available when you decide it is ready.',
            style: TextStyle(
              color: Color(0xFF7C2D12),
              fontWeight: FontWeight.w600,
              fontSize: 13,
              height: 1.4,
            ),
          ),
          if (notes != null) ...[
            const SizedBox(height: 10),
            Text(
              'Reason: $notes',
              key: const Key('ticket-kb-generation-notes'),
              style: const TextStyle(
                color: Color(0xFF9A3412),
                fontWeight: FontWeight.w700,
                fontSize: 12.5,
                height: 1.4,
              ),
            ),
          ],
          const SizedBox(height: 6),
          const Text(
            'This is a warning only. Staff can still publish after review.',
            style: TextStyle(
              color: DesignTokens.muted,
              fontWeight: FontWeight.w600,
              fontSize: 12,
              height: 1.35,
            ),
          ),
        ],
      ),
    );
  }
}
