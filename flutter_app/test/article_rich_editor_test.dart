import 'dart:typed_data';

import 'package:flutter/material.dart';
import 'package:flutter_localizations/flutter_localizations.dart';
import 'package:flutter_quill/flutter_quill.dart';
import 'package:flutter_quill/translations.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:aska_piyu/models/article_media_models.dart';
import 'package:aska_piyu/services/file_pick.dart';
import 'package:aska_piyu/widgets/article_rich_editor.dart';
import 'package:aska_piyu/widgets/safe_article_html.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  Future<void> pumpEditor(
    WidgetTester tester, {
    String content = '',
    String format = 'plain',
    Future<ArticleMediaItem> Function(PickedAppFile file)? onUploadImage,
    Future<PickedAppFile?> Function()? debugPickImage,
  }) async {
    await tester.pumpWidget(
      MaterialApp(
        localizationsDelegates: const [
          FlutterQuillLocalizations.delegate,
          GlobalMaterialLocalizations.delegate,
          GlobalWidgetsLocalizations.delegate,
          GlobalCupertinoLocalizations.delegate,
        ],
        home: Scaffold(
          body: SizedBox(
            width: 900,
            height: 700,
            child: ArticleRichEditor(
              key: const Key('test-editor'),
              initialContent: content,
              contentFormat: format,
              onUploadImage: onUploadImage,
              debugPickImage: debugPickImage,
            ),
          ),
        ),
      ),
    );
    await tester.pump();
  }

  ArticleRichEditorState editorState(WidgetTester tester) {
    return tester.state<ArticleRichEditorState>(find.byType(ArticleRichEditor));
  }

  Future<void> typeInEditor(WidgetTester tester, String text) async {
    final state = editorState(tester);
    final length = state.controller.document.length;
    state.controller.replaceText(
      0,
      length > 0 ? length - 1 : 0,
      text,
      TextSelection.collapsed(offset: text.length),
    );
    await tester.pump();
  }

  testWidgets('toolbar renders working controls', (tester) async {
    await pumpEditor(tester);
    expect(find.byKey(const Key('article-editor-toolbar')), findsOneWidget);
    expect(find.byKey(const Key('article-editor-style')), findsOneWidget);
    expect(find.byKey(const Key('article-editor-bold')), findsOneWidget);
    expect(find.byKey(const Key('article-editor-italic')), findsOneWidget);
    expect(find.byKey(const Key('article-editor-underline')), findsOneWidget);
    expect(find.byKey(const Key('article-editor-bullets')), findsOneWidget);
    expect(find.byKey(const Key('article-editor-numbered')), findsOneWidget);
    expect(find.byKey(const Key('article-editor-link')), findsOneWidget);
    expect(find.byKey(const Key('article-editor-image')), findsOneWidget);
    expect(find.byKey(const Key('article-editor-quote')), findsOneWidget);
    expect(find.byKey(const Key('article-editor-undo')), findsOneWidget);
    expect(find.byKey(const Key('article-editor-redo')), findsOneWidget);
  });

  testWidgets('bold italic underline persist', (tester) async {
    await pumpEditor(tester);
    await typeInEditor(tester, 'Bold text');
    editorState(tester).controller.updateSelection(
      TextSelection(
        baseOffset: 0,
        extentOffset: editorState(tester).controller.document.length - 1,
      ),
      ChangeSource.local,
    );
    await tester.tap(find.byKey(const Key('article-editor-bold')));
    await tester.pump();
    expect(editorState(tester).value.content, contains('<strong>'));

    await tester.tap(find.byKey(const Key('article-editor-italic')));
    await tester.pump();
    expect(editorState(tester).value.content, contains('<em>'));

    await tester.tap(find.byKey(const Key('article-editor-underline')));
    await tester.pump();
    expect(editorState(tester).value.content, contains('<u>'));
  });

  testWidgets('heading list quote and link persist', (tester) async {
    await pumpEditor(tester);
    await typeInEditor(tester, 'Title line');
    editorState(tester).controller.updateSelection(
      TextSelection(
        baseOffset: 0,
        extentOffset: editorState(tester).controller.document.length - 1,
      ),
      ChangeSource.local,
    );
    await tester.tap(find.byKey(const Key('article-editor-style')));
    await tester.pump();
    await tester.tap(find.text('Heading 1').last);
    await tester.pump();
    expect(editorState(tester).value.content, contains('<h1>'));

    await tester.tap(find.byKey(const Key('article-editor-bullets')));
    await tester.pump();
    expect(editorState(tester).value.content, contains('<ul>'));

    await tester.tap(find.byKey(const Key('article-editor-numbered')));
    await tester.pump();
    expect(editorState(tester).value.content, contains('<ol>'));

    await tester.tap(find.byKey(const Key('article-editor-quote')));
    await tester.pump();
    expect(editorState(tester).value.content, contains('<blockquote>'));

    await tester.tap(find.byKey(const Key('article-editor-link')));
    await tester.pump();
    await tester.enterText(
      find.byKey(const Key('article-editor-link-url')),
      'https://lspu.edu.ph',
    );
    await tester.tap(find.text('Apply'));
    await tester.pump();
    expect(editorState(tester).value.content, contains('https://lspu.edu.ph'));
  });

  testWidgets('undo redo restores typed text', (tester) async {
    await pumpEditor(tester);
    await typeInEditor(tester, 'Hello campus');
    editorState(tester).controller.updateSelection(
      TextSelection(
        baseOffset: 0,
        extentOffset: editorState(tester).controller.document.length - 1,
      ),
      ChangeSource.local,
    );
    await tester.tap(find.byKey(const Key('article-editor-bold')));
    await tester.pump();
    expect(editorState(tester).controller.hasUndo, isTrue);
    await tester.tap(find.byKey(const Key('article-editor-undo')));
    await tester.pump();
    expect(editorState(tester).controller.hasRedo, isTrue);
    await tester.tap(find.byKey(const Key('article-editor-redo')));
    await tester.pump();
    expect(editorState(tester).controller.hasUndo, isTrue);
  });

  testWidgets('old plain article opens without becoming html until formatted',
      (tester) async {
    await pumpEditor(
      tester,
      content: 'Students who are AWOL must report to OSA.',
      format: 'plain',
    );
    expect(editorState(tester).value.contentFormat, 'plain');
    expect(
      editorState(tester).value.content,
      contains('Students who are AWOL must report to OSA.'),
    );
  });

  testWidgets('inline image button uploads and inserts kb media url',
      (tester) async {
    await pumpEditor(
      tester,
      onUploadImage: (file) async => ArticleMediaItem(
        id: 'media-1',
        kind: 'inline_image',
        originalFilename: file.name,
        storedFilename: 'media-1_campus.png',
        contentType: 'image/png',
        sizeBytes: file.bytes.length,
        url: '/kb/media/media-1_campus.png',
      ),
      debugPickImage: () async => PickedAppFile(
        name: 'campus.png',
        bytes: Uint8List.fromList(List<int>.filled(16, 1)),
      ),
    );
    await tester.tap(find.byKey(const Key('article-editor-image')));
    await tester.pump();
    expect(editorState(tester).value.content, contains('/kb/media/media-1_campus.png'));
  });

  testWidgets('public html renderer shows heading bold list link and quote',
      (tester) async {
    await tester.pumpWidget(
      const MaterialApp(
        home: Scaffold(
          body: SafeArticleHtml(
            html:
                '<h2>Hours</h2><p>The desk is <strong>open</strong>.</p><ul><li>Bring ID</li></ul><blockquote>Quiet please.</blockquote><p><a href="https://lspu.edu.ph">LSPU</a></p>',
          ),
        ),
      ),
    );
    expect(find.text('Hours'), findsOneWidget);
    expect(find.textContaining('open'), findsWidgets);
    expect(find.textContaining('Bring ID'), findsOneWidget);
    expect(find.textContaining('Quiet please.'), findsOneWidget);
    expect(find.text('LSPU'), findsOneWidget);
    expect(find.textContaining('<h2>'), findsNothing);
  });
}