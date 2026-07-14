import 'dart:html' as html;

import '../models/admin_article_models.dart';
import 'admin_article_preview_export.dart';

void downloadArticlePreviewTxt({
  required AdminArticle article,
  required String bucketLabel,
  CandidateSummary? candidate,
  String? fallbackSourceFilename,
}) {
  final text = buildArticlePreviewTxt(
    article: article,
    bucketLabel: bucketLabel,
    candidate: candidate,
    fallbackSourceFilename: fallbackSourceFilename,
  );
  final filename = safePreviewFilename(
    title: article.title,
    bucketLabel: bucketLabel,
  );
  final blob = html.Blob([text], 'text/plain');
  final url = html.Url.createObjectUrlFromBlob(blob);
  html.AnchorElement(href: url)
    ..setAttribute('download', filename)
    ..click();
  html.Url.revokeObjectUrl(url);
}
