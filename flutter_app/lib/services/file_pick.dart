import 'dart:typed_data';

import 'package:file_picker/file_picker.dart';

class PickedAppFile {
  const PickedAppFile({
    required this.name,
    required this.bytes,
  });

  final String name;
  final Uint8List bytes;
}

Future<PickedAppFile?> pickAppFile({
  List<String>? allowedExtensions,
  String dialogTitle = 'Select a file',
}) async {
  final result = await FilePicker.pickFiles(
    type: allowedExtensions == null || allowedExtensions.isEmpty
        ? FileType.any
        : FileType.custom,
    allowedExtensions: allowedExtensions,
    withData: true,
    dialogTitle: dialogTitle,
  );
  if (result == null || result.files.isEmpty) return null;
  final file = result.files.single;
  final bytes = file.bytes;
  if (bytes == null || bytes.isEmpty) return null;
  final name = file.name.trim().isEmpty ? 'upload.bin' : file.name.trim();
  return PickedAppFile(name: name, bytes: bytes);
}
