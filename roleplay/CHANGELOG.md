# Changelog

## Upcoming Features

 - Add support for for pronouns. Currently, there is no way to retrieve pronouns from a discord.User profile
 - UI interface for editing settings. This may require creating an app command ('/settings') in order to utilize discords interaction objects and ephemeral messaging

## [2.6.0] - 2026-09-25

### Changed

- Consent questions (actions and becoming someone's Owner) are now answered with Yes/No buttons that only the members being asked can press, instead of typing a reply. Each question has its own buttons, so one answer can no longer answer several questions at once
- Using an action without a target (or with yourself) no longer asks you to consent to your own request
- Bots are no longer asked for consent, as they can't answer. This replaces the special case that only let administrators use actions on bots
- A Public Use target (or a Servant target, for `ask`) is no longer asked for consent after the invoker's Owner has already agreed
- `ask` accepts action aliases in any case, and lists the valid actions when given an unknown one
- `admin download` names files after their URL, skips images it has already saved, reports how many it downloaded, skipped or failed, and starts using them right away. Images saved by earlier versions are not recognized, so clear the cog's `images` data folder once before running it again

### Fixed

- The Selective setting never refused anything
- Settings commands waited 10 seconds before responding
- Reloading the cog failed because the action commands were left registered
- When both members' Owners were asked, a refusal always named the target's Owner, even when the other Owner declined
- Changes to your Owner list made while an Owner request was waiting for an answer could be lost
- Spoilered images were downloaded with TLS certificate checks turned off, and different images with the same file name overwrote each other in the cache. A spoilered image that can't be downloaded now shows the action without it instead of failing

### Removed

- Role-based denials (`denial` in action files). The configured roles never matched, so no action was ever denied
- Unused pronoun role lookups and role constants

## [2.5.43] - 2025-1-15

### Changed

- Removed author name from embed footer to make them less cluttered

## [2.5.42] - 2025-1-6

## Fixed

- Fixed years in changelog

### Changed

- Settings now shows in the same channel using button interaction with ephemeral mode
- Modified action command factory so they can be called both from the global scope [p]command_name as well as from under the roleplay group [p]rolepolay command_name. This also prevents all of the commands from being added to the redbot help menu under "No Category"


## [2.5.4] - 2024-12-25

### Changed

- Using [p]ask command will now always require consent from the targeted member (or their owner).

## [2.5.3] - 2024-12-22

### Changed

- We're now using the same extended valid yes/no responses When asking another user to become your owner

### Fixed

- Bug fixes.
- Fixed incorrect variable name in some of the consent timeout messages.

## [2.5.2] - 2024-12-21

### Fixed
- Fixed bug that would allow interactions between a command invoker and other member to skip consent if the invoker owner consented for double real I hope (You don't own everyone!!)

## [2.5.1] - 2024-12-20

### Added
- Added CustomMessagePredicate subclass to allow for more types of yes/no responses. It can also accept multiple users for check (allows reuse for owners, owner, or member to member)

### Changed
- Fixed bug that would allow interactions between a command invoker and other member to skip consent if the invoker owner consented (You don't own everyone!!)
- Member display names will now be bolded to make them more identifiable as a name and not a typo in some cases (the 'that jay' protocol)

## [2.5.0] - 2024-12-19

### Added
- Added "download" admin command. This caches all action gifs to a subfolder under the cog's config data folder

### Changed
- Action commands will look for local cached image directories and use a random image from those instead of the URLs when available

## [2.4.0] - 2024-12-16

### Added
- Added "Servant" flag to user settings. "Servants" will automatically consent to any request for them to perform an action on other members.

## [2.3.5] - 2024-12-16

### Fixed
- Fixed bug that would cause owner to be asked for consent twice (Are you *really* sure?)

### Added
- Error handling for operation that caches spoilered images

## [2.3.4] - 2024-12-16

### Changed
- Ask commands will ignore public use flag and ask the target member for consent when required

## [2.3.3] - 2024-12-16

### Added
- Added admin commands group
- Added logger_settings command group and logger_set_level command

## [2.3.2] - 2024-12-16

### Changed
- Changed some of the consent messages back to member.mention

### Fixed
- Fixed formatting issues in action YAML files
- made Action.aliases an optional property
- fixed interaction allowing consent to be skipped

## [2.3.1] - 2024-12-15

### Changed
- Changed many member.mention uses to member.display_name to reduce notifications
- Changed spoilered command images to use description as text message with cached spoiler image as attachment
- Simplified docstring for ask command function

### Fixed
- Fixed extra space in state settings checks (Ex: &roleplay settings public)

## [2.3.0] - 2024-12-14

### Added
- "ask" command. Ask another member to perform an action on yourself
- Added cooldown reset whenever an interaction is not successful

### Changed
- Major refactor of action command data
- Action consent messages all standardized to use the member who needs to respond as the first person in the messages
- Added 'active' and 'passive' consent messaging
- Added Action manager class and dataclasses for action properties
- Added Embed class for assembling embed objects in a cleaner way
- Embed can handle caching and attaching spoilered images to embed messages for a bit nicer presentation
- Changed consent validation to accommodate both owner and target having owners. Consent can only be obtained if both respond yes

### Fixed
- Fixed various typos in messages

## [1.0.0] - 2024-11-26

### Added
- Initial release with basic features and commands

### Changed
- Initial setup and configuration

### Fixed
- Initial bug fixes and improvements
