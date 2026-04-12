## Admin Panel Wireframe (Metinsel)

Bu dokuman, admin panelin temel ekranlarini ve alanlarini metinsel wireframe olarak tanimlar.

### 1. Login
```
+--------------------------------------------------+
| Admin Login                                      |
|--------------------------------------------------|
| Email: [_____________________________]           |
| Password: [__________________________]           |
| [ Sign In ]                                      |
+--------------------------------------------------+
```

### 2. Tenant Listesi
```
+--------------------------------------------------+
| Tenants                                          |
|--------------------------------------------------|
| [ + New Tenant ]   Search: [______________]      |
|--------------------------------------------------|
| Vestel    | Active | Users: 120 | [Edit] [View]  |
| Sony      | Active | Users: 85  | [Edit] [View]  |
| Demo      | Paused | Users: 3   | [Edit] [View]  |
+--------------------------------------------------+
```

### 3. Tenant Detayi
```
+--------------------------------------------------+
| Tenant: Vestel                                   |
|--------------------------------------------------|
| Status: [Active v]                               |
| Domain: vestel.com.tr                            |
| SSO: [Enabled v]                                 |
| Branding: [Logo Upload] [Theme Color]            |
|--------------------------------------------------|
| [Save Changes]                                   |
+--------------------------------------------------+
```

### 4. Agent Profile Editor
```
+--------------------------------------------------+
| Agent Profile                                    |
|--------------------------------------------------|
| Allowed Tools: [ search_file ] [ copy_file ] ... |
| Blocked Actions: [ delete_file ]                 |
| Allowed Folders:                                 |
|  - C:/Users/*/Desktop                            |
|  - C:/Users/*/Documents                          |
| Mail Whitelist: *@vestel.com.tr                  |
| Browser Domains: mail.google.com, calendar...    |
| Prompt Prefix:                                   |
|  [___________________________________________]   |
|--------------------------------------------------|
| [Save Profile]                                   |
+--------------------------------------------------+
```

### 5. Users
```
+--------------------------------------------------+
| Users (Vestel)                                   |
|--------------------------------------------------|
| [ + Invite User ]                                |
|--------------------------------------------------|
| ali@vestel.com.tr  | Active | Role: Admin        |
| ayse@vestel.com.tr | Active | Role: User         |
| mehmet@vestel.com  | Paused | Role: User         |
+--------------------------------------------------+
```

### 6. Audit Logs
```
+--------------------------------------------------+
| Audit Logs                                       |
|--------------------------------------------------|
| Filter: [Date] [User] [Action] [Status]          |
|--------------------------------------------------|
| 2026-04-12  | user@vestel | send_file | success  |
| 2026-04-12  | user@sony   | click_ui  | blocked  |
| 2026-04-12  | user@vestel | ticket    | created  |
+--------------------------------------------------+
```

### 7. Integrations
```
+--------------------------------------------------+
| Integrations                                     |
|--------------------------------------------------|
| Mail: [Gmail OAuth Connected] [Reconnect]        |
| Calendar: [Google Connected] [Reconnect]         |
| Ticketing: [Jira] [ServiceNow] [Zendesk]         |
|--------------------------------------------------|
| [Save Integration Settings]                      |
+--------------------------------------------------+
```

### 8. Feature Flags
```
+--------------------------------------------------+
| Feature Flags                                    |
|--------------------------------------------------|
| Agent Browser: [On]                              |
| PDF Link Click: [On]                             |
| Live Screen Share: [Off]                         |
|--------------------------------------------------|
| [Save Flags]                                     |
+--------------------------------------------------+
```
