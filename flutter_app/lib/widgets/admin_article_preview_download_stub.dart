import '../models/admin_article_models.dart';
import '../services/download_file.dart';
import 'admin_article_preview_export.dart';

Future<void> downloadArticlePreviewTxt({
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
  return downloadTextFile(filename: filename, text: text);
}

Future<void> downloadAllArticlePreviewsTxt({
  required List<ArticlePreviewExportEntry> entries,
  String? fallbackSourceFilename,
  String? scopeLabel,
  String? bucketLabel,
}) {
  final text = buildAllArticlePreviewsTxt(
    entries: entries,
    sourceFilename: fallbackSourceFilename,
    scopeLabel: scopeLabel,
  );
  final filename = safeAllPreviewsFilename(
    sourceFilename: fallbackSourceFilename,
    bucketLabel: bucketLabel ?? scopeLabel,
    count: entries.length,
  );
  return downloadTextFile(filename: filename, text: text);
}
