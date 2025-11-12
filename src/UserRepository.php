<?php

declare(strict_types=1);

final class UserRepository
{
    public function __construct(
        private readonly string $storageFile
    ) {
        if (!is_dir(dirname($this->storageFile))) {
            throw new RuntimeException('Verzeichnis für Benutzerspeicher existiert nicht.');
        }

        if (!file_exists($this->storageFile)) {
            $encodedEmpty = json_encode([], JSON_PRETTY_PRINT);
            if ($encodedEmpty === false) {
                throw new RuntimeException('Initiale Benutzerdaten konnten nicht serialisiert werden.');
            }

            if (file_put_contents($this->storageFile, $encodedEmpty, LOCK_EX) === false) {
                throw new RuntimeException('Initiale Benutzerdaten konnten nicht angelegt werden.');
            }
        }
    }

    /**
     * @return array<int, array{id:int,name:string}>
     */
    public function all(): array
    {
        $data = $this->read();
        usort($data, static fn (array $left, array $right): int => $left['id'] <=> $right['id']);

        return $data;
    }

    /**
     * @return array{id:int,name:string}
     */
    public function create(string $name): array
    {
        $users = $this->read();
        $nextId = $this->nextId($users);
        $user = ['id' => $nextId, 'name' => $name];
        $users[] = $user;
        $this->write($users);

        return $user;
    }

    public function delete(int $id): bool
    {
        $users = $this->read();
        $initialCount = count($users);
        $users = array_values(array_filter($users, static fn (array $user): bool => $user['id'] !== $id));

        if (count($users) === $initialCount) {
            return false;
        }

        $this->write($users);
        return true;
    }

    /**
     * @param array<int, array{id:int,name:string}> $users
     */
    private function nextId(array $users): int
    {
        $maxId = 0;
        foreach ($users as $user) {
            $maxId = max($maxId, (int)$user['id']);
        }

        return $maxId + 1;
    }

    /**
     * @return array<int, array{id:int,name:string}>
     */
    private function read(): array
    {
        $contents = file_get_contents($this->storageFile);
        if ($contents === false) {
            throw new RuntimeException('Benutzerdatei konnte nicht gelesen werden.');
        }

        try {
            $data = json_decode($contents, true, flags: JSON_THROW_ON_ERROR);
        } catch (\JsonException $exception) {
            throw new RuntimeException('Benutzerdaten sind beschädigt.', 0, $exception);
        }
        if (!is_array($data)) {
            return [];
        }

        return array_map(
            static fn (array $user): array => [
                'id' => (int)($user['id'] ?? 0),
                'name' => (string)($user['name'] ?? ''),
            ],
            $data
        );
    }

    /**
     * @param array<int, array{id:int,name:string}> $users
     */
    private function write(array $users): void
    {
        $encoded = json_encode($users, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE);
        if ($encoded === false) {
            throw new RuntimeException('Benutzerdaten konnten nicht serialisiert werden.');
        }

        if (file_put_contents($this->storageFile, $encoded, LOCK_EX) === false) {
            throw new RuntimeException('Benutzerdaten konnten nicht gespeichert werden.');
        }
    }
}
