import 'package:flutter_test/flutter_test.dart';

import 'package:aska_piyu/widgets/article_html_codec.dart';

void main() {
  test('plain text stays plain and round-trips', () {
    final doc = documentFromArticleContent(
      content: 'Overview\nStudents must report to OSA.',
      contentFormat: 'plain',
    );
    final value = editorValueFromDocument(doc, existingFormat: 'plain');
    expect(value.contentFormat, 'plain');
    expect(value.content, contains('Students must report to OSA.'));
    expect(documentHasRichFormatting(doc), isFalse);
  });

  test('bold italic underline heading list link quote persist in HTML', () {
    final html = '<h2>Hours</h2>'
        '<p>The library is <strong>open</strong> <em>today</em> and '
        '<u>tomorrow</u>.</p>'
        '<ul><li>Bring ID</li></ul>'
        '<ol><li>Sign in</li></ol>'
        '<p><a href="https://lspu.edu.ph">LSPU</a></p>'
        '<blockquote>Quiet study only.</blockquote>';
    final doc = documentFromArticleContent(
      content: html,
      contentFormat: 'html',
    );
    final value = editorValueFromDocument(doc, existingFormat: 'html');
    expect(value.contentFormat, 'html');
    expect(value.content, contains('<strong>'));
    expect(value.content, contains('<em>'));
    expect(value.content, contains('<u>'));
    expect(value.content, contains('<h2>'));
    expect(value.content, contains('<ul>'));
    expect(value.content, contains('<ol>'));
    expect(value.content, contains('https://lspu.edu.ph'));
    expect(value.content, contains('<blockquote>'));
    expect(value.content.toLowerCase(), isNot(contains('javascript:')));
  });

  test('javascript links and remote images are stripped on export', () {
    final html = '<p><a href="javascript:alert(1)">x</a>'
        '<a href="https://lspu.edu.ph">ok</a>'
        '<img src="https://evil.example/x.png">'
        '<img src="/kb/media/abc.png"></p>';
    final doc = documentFromArticleContent(
      content: html,
      contentFormat: 'html',
    );
    final exported = editorValueFromDocument(doc, existingFormat: 'html').content;
    expect(exported, isNot(contains('javascript:')));
    expect(exported, contains('https://lspu.edu.ph'));
    expect(exported, contains('/kb/media/abc.png'));
    expect(exported, isNot(contains('evil.example')));
  });

  test('protocol-relative and javascript hrefs are rejected', () {
    expect(safeArticleHref('javascript:alert(1)'), isNull);
    expect(safeArticleHref('//evil.example/phish'), isNull);
    expect(safeArticleHref('https://lspu.edu.ph'), 'https://lspu.edu.ph');
    expect(safeArticleHref('/kb/media/abc.png'), '/kb/media/abc.png');
  });

  test('inline image HTML is preserved', () {
    final html = '<p>See map</p><p><img src="/kb/media/campus.png" alt=""></p>';
    final doc = documentFromArticleContent(
      content: html,
      contentFormat: 'html',
    );
    final value = editorValueFromDocument(doc, existingFormat: 'html');
    expect(value.content, contains('/kb/media/campus.png'));
    expect(documentHasRichFormatting(doc), isTrue);
  });

  test('html to plain strips tags for empty checks', () {
    expect(articleHtmlToPlain('<p></p>').trim(), isEmpty);
    expect(articleHtmlToPlain('<h2>Hours</h2><p>Open <strong>8am</strong></p>'),
        'Hours\nOpen 8am');
  });
}
