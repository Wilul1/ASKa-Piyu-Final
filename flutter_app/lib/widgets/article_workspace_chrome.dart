import 'dart:convert';

import 'package:flutter/material.dart';

import '../app_config.dart';
import '../auth/auth_state.dart';
import '../design_tokens.dart';
import '../services/api_client.dart';

class ArticleWorkspaceHeader extends StatelessWidget {
  const ArticleWorkspaceHeader({
    super.key,
    required this.stacked,
    required this.onBack,
    required this.breadcrumbCurrent,
    required this.title,
    required this.subtitle,
    this.backButtonKey,
  });

  final bool stacked;
  final VoidCallback? onBack;
  final String breadcrumbCurrent;
  final String title;
  final String subtitle;
  final Key? backButtonKey;

  @override
  Widget build(BuildContext context) {
    final copy = Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text.rich(
          TextSpan(
            style: const TextStyle(
              color: DesignTokens.muted,
              fontSize: 12,
              fontWeight: FontWeight.w700,
            ),
            children: [
              const TextSpan(text: 'Knowledge Base'),
              TextSpan(
                text: '  >  ',
                style: TextStyle(
                  color: DesignTokens.muted.withValues(alpha: 0.7),
                ),
              ),
              TextSpan(
                text: breadcrumbCurrent,
                style: const TextStyle(color: DesignTokens.ink),
              ),
            ],
          ),
        ),
        const SizedBox(height: 8),
        Text(
          title,
          style: const TextStyle(
            color: DesignTokens.ink,
            fontSize: 28,
            fontWeight: FontWeight.w900,
            height: 1.1,
          ),
        ),
        const SizedBox(height: 6),
        Text(
          subtitle,
          style: const TextStyle(
            color: DesignTokens.muted,
            fontSize: 13,
            fontWeight: FontWeight.w600,
            height: 1.35,
          ),
        ),
      ],
    );
    final back = TextButton.icon(
      key: backButtonKey,
      onPressed: onBack,
      icon: const Icon(Icons.arrow_back, size: 18),
      label: const Text(
        'Back to Articles',
        style: TextStyle(fontWeight: FontWeight.w800),
      ),
      style: TextButton.styleFrom(
        foregroundColor: DesignTokens.ink,
        backgroundColor: Colors.white,
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(10),
          side: const BorderSide(color: DesignTokens.border),
        ),
      ),
    );

    if (stacked) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          copy,
          const SizedBox(height: 12),
          Align(alignment: Alignment.centerLeft, child: back),
        ],
      );
    }
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Expanded(child: copy),
        const SizedBox(width: 12),
        back,
      ],
    );
  }
}

class ArticleWorkspacePanel extends StatelessWidget {
  const ArticleWorkspacePanel({
    super.key,
    required this.title,
    required this.subtitle,
    required this.child,
  });

  final String title;
  final String subtitle;
  final Widget child;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.fromLTRB(18, 16, 18, 18),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: DesignTokens.border),
        boxShadow: DesignTokens.softShadow(0.03),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          Text(
            title,
            style: const TextStyle(
              color: DesignTokens.ink,
              fontSize: 16,
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 4),
          Text(
            subtitle,
            style: const TextStyle(
              color: DesignTokens.muted,
              fontSize: 12,
              fontWeight: FontWeight.w600,
              height: 1.35,
            ),
          ),
          const SizedBox(height: 14),
          child,
        ],
      ),
    );
  }
}

Widget articleLabeledField({
  required String label,
  required Widget child,
  bool required = false,
  String? helper,
}) {
  return Column(
    crossAxisAlignment: CrossAxisAlignment.start,
    children: [
      Row(
        children: [
          Text(
            label,
            style: const TextStyle(
              color: DesignTokens.ink,
              fontSize: 13,
              fontWeight: FontWeight.w800,
            ),
          ),
          if (required)
            const Text(
              ' *',
              style: TextStyle(
                color: DesignTokens.maroon,
                fontSize: 13,
                fontWeight: FontWeight.w800,
              ),
            ),
        ],
      ),
      const SizedBox(height: 6),
      child,
      if (helper != null) ...[
        const SizedBox(height: 6),
        Text(
          helper,
          style: const TextStyle(
            color: DesignTokens.muted,
            fontSize: 11,
            fontWeight: FontWeight.w600,
          ),
        ),
      ],
    ],
  );
}

InputDecoration articleInputDecoration({
  String? hint,
  String? helper,
}) {
  return InputDecoration(
    hintText: hint,
    helperText: helper,
    isDense: true,
    filled: true,
    fillColor: const Color(0xFFF8FAFC),
    contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
    border: OutlineInputBorder(
      borderRadius: BorderRadius.circular(10),
      borderSide: const BorderSide(color: DesignTokens.border),
    ),
    enabledBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(10),
      borderSide: const BorderSide(color: DesignTokens.border),
    ),
    focusedBorder: OutlineInputBorder(
      borderRadius: BorderRadius.circular(10),
      borderSide: const BorderSide(color: DesignTokens.maroon, width: 1.2),
    ),
  );
}

String formatArticleTimestamp(String? raw) {
  if (raw == null || raw.trim().isEmpty) return '';
  final parsed = DateTime.tryParse(raw.trim());
  if (parsed == null) return raw.trim();
  final local = parsed.toLocal();
  const months = [
    'Jan',
    'Feb',
    'Mar',
    'Apr',
    'May',
    'Jun',
    'Jul',
    'Aug',
    'Sep',
    'Oct',
    'Nov',
    'Dec',
  ];
  final hour = local.hour % 12 == 0 ? 12 : local.hour % 12;
  final minute = local.minute.toString().padLeft(2, '0');
  final period = local.hour >= 12 ? 'PM' : 'AM';
  return '${months[local.month - 1]} ${local.day}, ${local.year} - $hour:$minute $period';
}

Future<List<String>> loadTicketOfficeNames(BuildContext context) async {
  final result = await ApiClient.send(
    method: 'GET',
    url: '${AppConfig.resolvedApiBase}/tickets/offices',
    headers: AuthScope.of(context).ticketHeaders(),
  );
  final decoded = result.json;
  Map<String, dynamic> data;
  if (decoded is Map<String, dynamic>) {
    data = decoded;
  } else if (decoded is Map) {
    data = Map<String, dynamic>.from(decoded);
  } else {
    try {
      final parsed = jsonDecode(result.body);
      data = parsed is Map
          ? Map<String, dynamic>.from(parsed)
          : <String, dynamic>{};
    } catch (_) {
      data = <String, dynamic>{};
    }
  }
  if (!result.ok) {
    throw StateError('Could not load offices.');
  }
  final items = data['items'] is List ? data['items'] as List : const [];
  final names = items
      .whereType<Map>()
      .map((item) => (item['name'] ?? '').toString().trim())
      .where((name) => name.isNotEmpty)
      .toSet()
      .toList()
    ..sort();
  return names;
}
