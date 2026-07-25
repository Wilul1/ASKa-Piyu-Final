import 'download_file_stub.dart'
    if (dart.library.html) 'download_file_web.dart' as impl;

Future<void> downloadTextFile({
  required String filename,
  required String text,
  String mimeType = 'text/plain',
}) {
  return impl.downloadTextFile(
    filename: filename,
    text: text,
    mimeType: mimeType,
  );
}

Future<void> downloadBytesFile({
  required String filename,
  required List<int> bytes,
  String mimeType = 'application/octet-stream',
}) {
  return impl.downloadBytesFile(
    filename: filename,
    bytes: bytes,
    mimeType: mimeType,
  );
}
