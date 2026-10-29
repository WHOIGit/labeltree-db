# Spec Delta

## Purpose

Guides a site admin through starting a new instance in the web app: creating
the first organization, adding its users and importing its first trees.

## ADDED Requirements

### Requirement: Setup wizard offered on an empty instance
While the instance has no trees, the home page SHALL send a logged-in site
admin to the setup wizard at `/setup/`. Other users SHALL see a page saying the
instance has no trees yet and that a site admin sets it up. Once a tree
exists, the home page SHALL behave as before, and `/setup/` SHALL send site
admins to the home page.

#### Scenario: Site admin on a new instance
- **WHEN** a site admin opens `/` on an instance with no trees
- **THEN** they are sent to `/setup/`

#### Scenario: Another user on a new instance
- **WHEN** a logged-in user who is not a site admin opens `/` on an instance with no trees
- **THEN** the page says there are no trees yet and that a site admin sets the instance up

#### Scenario: Setup after the first tree
- **WHEN** a site admin opens `/setup/` and a tree exists
- **THEN** they are sent to the home page, which shows the first tree

### Requirement: Setup wizard access
`/setup/` SHALL be for site admins only: anonymous users SHALL be sent to the
login page, and other logged-in users SHALL get the "not allowed" page.

#### Scenario: Anonymous setup
- **WHEN** an anonymous browser opens `/setup/`
- **THEN** it is redirected to the login page

#### Scenario: Owner opens setup
- **WHEN** an organization owner who is not a site admin opens `/setup/`
- **THEN** the page returns `403` and explains that only site admins set up the instance

### Requirement: Setup steps
The wizard SHALL have three steps in order: Organization, Users and Trees.
It SHALL open at the Users step when exactly one organization exists, with it
picked, and at the Organization step otherwise. Each step SHALL offer Skip,
which moves on without changes, except the Organization step while no
organization is picked. Skipping Trees SHALL go to the organization's page.

#### Scenario: Resuming after creating an organization
- **WHEN** a site admin who created organization `lab_a` in the wizard reopens `/setup/` with no trees yet
- **THEN** the wizard opens at the Users step with `lab_a` picked

#### Scenario: Skipping users
- **WHEN** the site admin clicks Skip on the Users step
- **THEN** the Trees step is shown and no member was added

#### Scenario: No organization yet
- **WHEN** the wizard opens on an instance with no organization
- **THEN** the Organization step is shown and its Skip is disabled

#### Scenario: Skipping trees
- **WHEN** the site admin clicks Skip on the Trees step of organization `lab_a`
- **THEN** the organization page of `lab_a` is shown

### Requirement: Organization step
The Organization step SHALL create an organization from a slug id and a name.
An id that is not a slug, an empty name or an existing id SHALL be reported in
the step without leaving it. When organizations already exist, the step SHALL
also let the site admin pick one instead.

#### Scenario: First organization
- **WHEN** the site admin enters id `lab_a` and name `Lab A` and continues
- **THEN** organization `lab_a` exists and the Users step is shown for it

#### Scenario: Existing organization id
- **WHEN** the site admin enters an id that is already an organization
- **THEN** the step shows that the id is taken and stays on the Organization step

### Requirement: Users step
The Users step SHALL add members to the picked organization, one at a time,
each with a username and a role. For a username with no account, the step SHALL
ask for an initial password and create the account first. The step SHALL list
the members added so far, and Continue SHALL move to the Trees step. Leaving
the step with a username typed but not added SHALL ask before discarding it.

#### Scenario: Adding a new user
- **WHEN** the site admin adds username `curator1` with role `owner` and an initial password, and no account `curator1` exists
- **THEN** account `curator1` exists with that password and is `owner` of the organization

#### Scenario: Adding an existing user
- **WHEN** the site admin adds an existing user `drafter1` with role `drafter`
- **THEN** `drafter1` is `drafter` of the organization and their password is unchanged

#### Scenario: Leaving with a username not added
- **WHEN** the site admin has typed `curator1` without adding it and clicks Continue or Skip
- **THEN** a dialog asks whether to discard `curator1`; Go back keeps it in the form, and Discard and continue moves to the Trees step without creating anything

#### Scenario: Weak initial password
- **WHEN** the site admin gives an initial password the site's password rules refuse
- **THEN** the step shows the reasons and no account is created

### Requirement: Trees step
The Trees step SHALL import a tree into the picked organization from a tree
id, a title, an optional description and import JSON, which is pasted into a
text box or loaded from a file into it. The import format SHALL be that of the
draft editor's import. Each published tree SHALL be listed, and the step SHALL
allow importing another. Leaving by Skip or Done with a tree typed but not
imported, or saved but not published, SHALL ask first.

#### Scenario: Importing a tree
- **WHEN** the site admin enters tree id `lab_taxonomy`, title `Lab taxonomy` and valid import JSON, and imports
- **THEN** tree `lab_taxonomy` exists in the organization at revision 1 with the file's nodes, and the step lists it

#### Scenario: Loading a file
- **WHEN** the site admin picks a JSON file
- **THEN** its contents appear in the text box, where they can be edited before importing

#### Scenario: Leaving with a tree not imported
- **WHEN** the form holds tree id `lab_more` and its JSON, not imported, and the site admin clicks Done
- **THEN** a dialog asks whether to discard `lab_more`; Go back keeps the form, and confirming leaves without creating the tree

#### Scenario: Leaving with an unpublished draft
- **WHEN** an import was saved as a draft but its publish failed, and the site admin clicks Skip
- **THEN** a dialog says the tree is saved as a draft but not published, and confirming leaves it as a draft

#### Scenario: Importing a second tree
- **WHEN** the site admin imports a second tree after the first
- **THEN** both trees are listed and both exist

### Requirement: Import checks
An import SHALL be checked before anything is stored. Malformed JSON or a file
not in the import format SHALL be reported with its position; a taken tree id
or structural errors, such as duplicate or unsafe labels, SHALL be listed. In
each case nothing SHALL be created.

#### Scenario: Malformed file
- **WHEN** the import JSON has a node without a `label`
- **THEN** the step reports the node's position, such as `nodes[1].children[0]`, and no changeset or tree is created

#### Scenario: Duplicate labels
- **WHEN** the import JSON has two nodes labelled `detritus`
- **THEN** the step lists the duplicate label error and no changeset or tree is created

#### Scenario: Taken tree id
- **WHEN** the tree id entered is already a tree
- **THEN** the step reports that the tree exists and nothing is created

### Requirement: WoRMS records during import
Before publishing, the import SHALL fetch the WoRMS records of its AphiaIDs
that aren't cached, showing the job progress used elsewhere in the web app.
AphiaIDs that still fail SHALL be listed with Try again and Proceed anyway;
proceeding SHALL publish with those placement checks unavailable.

#### Scenario: Import with AphiaIDs
- **WHEN** the import JSON has AphiaIDs whose records aren't cached
- **THEN** the step shows the fetch job's progress, then publishes the tree with its WoRMS warnings computed

#### Scenario: WoRMS unreachable
- **WHEN** an AphiaID's record can't be fetched after its retries
- **THEN** the step lists it with Try again and Proceed anyway, and Proceed anyway publishes the tree
