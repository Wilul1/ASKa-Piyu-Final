import 'print_helper_stub.dart'
    if (dart.library.html) 'print_helper_web.dart' as impl;

void printCurrentDocument() => impl.printCurrentDocument();
