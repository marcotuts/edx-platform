;(function (define) {
    'use strict';
    define([
        'backbone',
        'teams/js/views/team_card',
        'common/js/components/views/paginated_view',
        'teams/js/views/team_actions',
        'teams/js/views/team_utils'
    ], function (Backbone, TeamCardView, PaginatedView, TeamActionsView, TeamUtils) {
        var TeamsView = PaginatedView.extend({
            type: 'teams',

            initialize: function (options) {
                this.topic = options.topic;
                this.itemViewClass = TeamCardView.extend({
                    router: options.router,
                    topic: options.topic,
                    maxTeamSize: options.maxTeamSize,
                    countries: TeamUtils.selectorOptionsArrayToHashWithBlank(options.teamParams.countries),
                    languages: TeamUtils.selectorOptionsArrayToHashWithBlank(options.teamParams.languages)
                });
                PaginatedView.prototype.initialize.call(this);
                this.teamParams = options.teamParams;
                this.showActions = options.showActions;
            },

            render: function () {
                PaginatedView.prototype.render.call(this);

                if (this.showActions === true) {
                    var teamActionsView = new TeamActionsView({
                        teamParams: this.teamParams
                    });
                    this.$el.append(teamActionsView.$el);
                    teamActionsView.render();
                }

                return this;
            }
        });
        return TeamsView;
    });
}).call(this, define || RequireJS.define);
