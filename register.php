<?php

declare(strict_types=1);

require_once __DIR__ . '/src/UserRepository.php';

$repository = new UserRepository(__DIR__ . '/data/users.json');

$errors = [];
$messages = [];

if ($_SERVER['REQUEST_METHOD'] === 'POST') {
    $action = $_POST['action'] ?? '';

    if ($action === 'delete') {
        $userId = filter_input(INPUT_POST, 'user_id', FILTER_VALIDATE_INT);

        if ($userId === false || $userId === null) {
            $errors[] = 'Ungültige Benutzer-ID.';
        } else {
            try {
                $deleted = $repository->delete($userId);
                if ($deleted) {
                    $messages[] = 'Benutzer wurde erfolgreich gelöscht.';
                } else {
                    $errors[] = 'Benutzer wurde nicht gefunden.';
                }
            } catch (RuntimeException $exception) {
                $errors[] = 'Benutzer konnte nicht gelöscht werden.';
            }
        }
    } elseif ($action === 'create') {
        $name = trim((string)($_POST['name'] ?? ''));

        if ($name === '') {
            $errors[] = 'Der Benutzername darf nicht leer sein.';
        } else {
            $user = $repository->create($name);
            $messages[] = sprintf('Benutzer "%s" wurde angelegt.', $user['name']);
        }
    }
}

try {
    $users = $repository->all();
} catch (RuntimeException $exception) {
    $errors[] = 'Benutzerdaten konnten nicht geladen werden.';
    $users = [];
}

?>
<!DOCTYPE html>
<html lang="de">
<head>
    <meta charset="UTF-8">
    <title>Benutzerverwaltung</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 2rem; }
        .messages { margin-bottom: 1rem; }
        .messages p { padding: 0.5rem; border-radius: 4px; }
        .messages .error { background-color: #fbeaea; color: #b30000; }
        .messages .success { background-color: #e3f6e8; color: #0b6623; }
        table { border-collapse: collapse; width: 100%; margin-top: 1rem; }
        th, td { border: 1px solid #ddd; padding: 0.5rem; text-align: left; }
        form.inline { display: inline; }
    </style>
</head>
<body>
<h1>Benutzerverwaltung</h1>
<div class="messages">
    <?php foreach ($errors as $error): ?>
        <p class="error"><?php echo htmlspecialchars($error, ENT_QUOTES | ENT_SUBSTITUTE); ?></p>
    <?php endforeach; ?>
    <?php foreach ($messages as $message): ?>
        <p class="success"><?php echo htmlspecialchars($message, ENT_QUOTES | ENT_SUBSTITUTE); ?></p>
    <?php endforeach; ?>
</div>

<form method="post">
    <input type="hidden" name="action" value="create">
    <label>
        Neuer Benutzer:
        <input type="text" name="name" required>
    </label>
    <button type="submit">Anlegen</button>
</form>

<table>
    <thead>
    <tr>
        <th>ID</th>
        <th>Name</th>
        <th>Aktionen</th>
    </tr>
    </thead>
    <tbody>
    <?php foreach ($users as $user): ?>
        <tr>
            <td><?php echo htmlspecialchars((string)$user['id'], ENT_QUOTES | ENT_SUBSTITUTE); ?></td>
            <td><?php echo htmlspecialchars($user['name'], ENT_QUOTES | ENT_SUBSTITUTE); ?></td>
            <td>
                <form method="post" class="inline">
                    <input type="hidden" name="action" value="delete">
                    <input type="hidden" name="user_id" value="<?php echo htmlspecialchars((string)$user['id'], ENT_QUOTES | ENT_SUBSTITUTE); ?>">
                    <button type="submit">Löschen</button>
                </form>
            </td>
        </tr>
    <?php endforeach; ?>
    </tbody>
</table>
</body>
</html>
