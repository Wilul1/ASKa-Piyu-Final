import 'package:flutter_test/flutter_test.dart';

import 'package:aska_piyu/services/kb_compose_helpers.dart';

void main() {
  test('cleanAnswerForPublic strips greetings and PII', () {
    const raw = '''
Good day!
Thank you for your inquiry regarding the Issuance of Good Moral Certificate.

Please be guided as follows:
Office: OSAS
Fee: P30.00
Student number: 2024-12345
Email me at clerk@lspu.edu.ph if needed.

Best regards
OSAS Staff
''';
    final cleaned = cleanAnswerForPublic(raw);
    expect(cleaned.toLowerCase(), isNot(contains('good day')));
    expect(cleaned.toLowerCase(), isNot(contains('thank you for your inquiry')));
    expect(cleaned.toLowerCase(), isNot(contains('please be guided')));
    expect(cleaned, contains('Office: OSAS'));
    expect(cleaned, contains('Fee: P30.00'));
    expect(cleaned, contains('[student id redacted]'));
    expect(cleaned, contains('[email redacted]'));
    expect(cleaned.toLowerCase(), isNot(contains('best regards')));
  });

  test('cleanFaqTitle turns ticket subject into FAQ title', () {
    expect(
      cleanFaqTitle(
        'Need steps and fee for Issuance of Good Moral Certificate (Undergraduate)',
      ),
      'Issuance of Good Moral Certificate (Undergraduate)',
    );
    expect(cleanFaqTitle('How do I get an excuse slip?'), 'Get an excuse slip');
  });

  test('insertFaqSection adds missing headings only once', () {
    const base = '## Question\n\nTopic\n\n## Answer\n\nDetails.';
    final withFees = insertFaqSection(base, '## Fees', '- Amount');
    expect(withFees, contains('## Fees'));
    expect(withFees, contains('- Amount'));
    final again = insertFaqSection(withFees, '## Fees', '- Amount');
    expect(again, withFees);
  });

  test('buildCleanPublicArticleBody uses cleaned title and answer', () {
    final body = buildCleanPublicArticleBody(
      subject: 'Need steps and fee for Dropping of Subjects',
      answer: 'Good day!\nFee is P30 per unit.\nThank you for your inquiry.',
    );
    expect(body, contains('## Question'));
    expect(body, contains('Dropping of Subjects'));
    expect(body, contains('## Answer'));
    expect(body, contains('Fee is P30 per unit.'));
    expect(body.toLowerCase(), isNot(contains('good day')));
  });
}
