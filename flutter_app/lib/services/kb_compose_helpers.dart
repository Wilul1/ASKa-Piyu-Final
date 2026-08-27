/// Helpers for ticket → public KB article composition.

const faqTemplateSections = <({String label, String heading, String hint})>[
  (
    label: 'Requirements',
    heading: '## Requirements',
    hint: '- Document or eligibility item\n- …',
  ),
  (
    label: 'Steps',
    heading: '## Steps',
    hint: '1. …\n2. …\n3. …',
  ),
  (
    label: 'Fees',
    heading: '## Fees',
    hint: '- Amount and where to pay\n- …',
  ),
  (
    label: 'Where to go',
    heading: '## Where to go',
    hint: '- Office name and location / window\n- …',
  ),
  (
    label: 'Processing time',
    heading: '## Processing time',
    hint: '- Typical working days / claim schedule\n- …',
  ),
];

final _greetingLineRe = RegExp(
  r'^\s*(good\s+(day|morning|afternoon|evening)|hi\b|hello\b|dear\b|'
  r'thank\s+you\s+for\s+your\s+(inquiry|concern|message|email)|'
  r'thanks\s+for\s+(reaching\s+out|your\s+inquiry)|'
  r'please\s+be\s+guided\s+as\s+follows\s*:?|'
  r'we\s+hope\s+this\s+helps|best\s+regards|respectfully|sincerely|'
  r'osas\s+staff|office\s+staff)\b.*$',
  caseSensitive: false,
);

final _emailRe = RegExp(
  r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b',
);

final _phoneRe = RegExp(r'\b(?:09|\+639)\d{9}\b');

final _studentIdRe = RegExp(
  r'\b(?:student\s*(?:number|id|no\.?)|id\s*no\.?)\s*[:#]?\s*[A-Za-z0-9\-_/]+\b',
  caseSensitive: false,
);

final _needTitleRe = RegExp(
  r'^\s*(?:need|requesting|looking\s+for)\s+(?:the\s+)?'
  r'(?:steps?(?:\s+and\s+fee)?|info(?:rmation)?|details?|help)\s+'
  r'(?:and\s+fee\s+)?(?:for|about|on)\s+',
  caseSensitive: false,
);

final _howTitleRe = RegExp(
  r'^\s*(?:how\s+(?:do\s+i|to|can\s+i)|what\s+(?:is|are)|where\s+(?:do\s+i|can\s+i))\s+',
  caseSensitive: false,
);

/// Turn a chatty office reply into cleaner public FAQ wording.
String cleanAnswerForPublic(String raw) {
  final lines = raw.replaceAll('\r\n', '\n').split('\n');
  final kept = <String>[];
  for (final line in lines) {
    final trimmed = line.trimRight();
    if (trimmed.trim().isEmpty) {
      if (kept.isNotEmpty && kept.last.trim().isNotEmpty) kept.add('');
      continue;
    }
    if (_greetingLineRe.hasMatch(trimmed.trim())) continue;
    var cleaned = trimmed;
    cleaned = cleaned.replaceAll(_emailRe, '[email redacted]');
    cleaned = cleaned.replaceAll(_phoneRe, '[phone redacted]');
    cleaned = cleaned.replaceAll(_studentIdRe, '[student id redacted]');
    kept.add(cleaned);
  }
  while (kept.isNotEmpty && kept.first.trim().isEmpty) {
    kept.removeAt(0);
  }
  while (kept.isNotEmpty && kept.last.trim().isEmpty) {
    kept.removeLast();
  }
  return kept.join('\n').replaceAll(RegExp(r'\n{3,}'), '\n\n').trim();
}

/// Prefer a FAQ-style title over a ticket chat question.
String cleanFaqTitle(String raw) {
  var title = raw.trim().replaceAll(RegExp(r'\s+'), ' ');
  if (title.endsWith('?')) {
    title = title.substring(0, title.length - 1).trim();
  }
  title = title.replaceFirst(_needTitleRe, '');
  title = title.replaceFirst(_howTitleRe, '');
  title = title.trim();
  if (title.isEmpty) return raw.trim();
  return title[0].toUpperCase() + title.substring(1);
}

/// Build a public FAQ body from the ticket subject and cleaned office answer.
String buildCleanPublicArticleBody({
  required String subject,
  required String answer,
}) {
  final title = cleanFaqTitle(subject);
  final cleaned = cleanAnswerForPublic(answer);
  final body = cleaned.isEmpty ? answer.trim() : cleaned;
  return '## Question\n\n$title\n\n## Answer\n\n$body';
}

String shortPublicSummary(String answer, {int limit = 180}) {
  final cleaned = cleanAnswerForPublic(answer).replaceAll('\n', ' ').trim();
  final source = cleaned.isEmpty ? answer.trim() : cleaned;
  if (source.length <= limit) return source;
  return '${source.substring(0, limit - 1).trimRight()}…';
}

/// Insert a FAQ section template if that heading is not already present.
String insertFaqSection(String content, String heading, String hint) {
  final existing = content;
  if (existing.toLowerCase().contains(heading.toLowerCase())) {
    return existing;
  }
  final block = '\n\n$heading\n\n$hint\n';
  final answerIdx = existing.toLowerCase().indexOf('## answer');
  if (answerIdx >= 0) {
    // Append after the Answer section content (end of doc is fine).
    return '${existing.trimRight()}$block';
  }
  return '${existing.trimRight()}$block';
}
