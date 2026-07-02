import 'package:flutter/material.dart';
import 'auth/auth_state.dart';
import 'screens/student_home.dart';
import 'design_tokens.dart';

void main() {
  runApp(const MyApp());
}

class MyApp extends StatefulWidget {
  const MyApp({super.key});

  @override
  State<MyApp> createState() => _MyAppState();
}

class _MyAppState extends State<MyApp> {
  final AuthController _authController = AuthController();

  @override
  void initState() {
    super.initState();
    _authController.loadCurrentUser();
  }

  @override
  void dispose() {
    _authController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AuthScope(
      controller: _authController,
      child: MaterialApp(
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
