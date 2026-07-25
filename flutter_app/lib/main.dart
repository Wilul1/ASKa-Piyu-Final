import 'package:flutter/material.dart';
import 'app_config.dart';
import 'auth/auth_state.dart';
import 'auth/session_expiry.dart';
import 'screens/student_home.dart';
import 'design_tokens.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await AppConfig.init();
  runApp(const MyApp());
}

class MyApp extends StatefulWidget {
  const MyApp({super.key});

  @override
  State<MyApp> createState() => _MyAppState();
}

class _MyAppState extends State<MyApp> {
  final AuthController _authController = AuthController();
  final GlobalKey<NavigatorState> _navigatorKey = GlobalKey<NavigatorState>();

  @override
  void initState() {
    super.initState();
    SessionExpiry.bind(
      auth: _authController,
      navigatorKey: _navigatorKey,
    );
    _authController.loadCurrentUser();
  }

  @override
  void dispose() {
    SessionExpiry.unbind();
    _authController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AuthScope(
      controller: _authController,
      child: MaterialApp(
        navigatorKey: _navigatorKey,
        title: 'ASKa-Piyu',
        theme: ThemeData(
          primaryColor: DesignTokens.maroon,
          scaffoldBackgroundColor: DesignTokens.bgGrey,
          colorScheme: ColorScheme.fromSeed(
            seedColor: DesignTokens.maroon,
            primary: DesignTokens.maroon,
            secondary: DesignTokens.gold,
            surface: Colors.white,
          ),
          appBarTheme: const AppBarTheme(
            backgroundColor: Colors.white,
            foregroundColor: DesignTokens.maroon,
            elevation: 0.5,
          ),
          textTheme: const TextTheme(
            headlineLarge: DesignTokens.h1,
            bodyMedium: DesignTokens.body,
          ),
        ),
        home: const StudentHomePage(),
      ),
    );
  }
}
