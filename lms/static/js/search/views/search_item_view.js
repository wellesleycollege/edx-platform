;(function (define) {

define([
    'jquery',
    'underscore',
    'backbone',
    'gettext',
    'logger'
], function ($, _, Backbone, gettext, Logger) {
   'use strict';

    return Backbone.View.extend({

        tagName: 'li',
        className: 'search-results-item',
        attributes: {
            'role': 'region',
            'aria-label': 'search result'
        },

        events: {
            'click .search-results-item a': 'logSearchItem',
        },

        initialize: function () {
            this.tpl = _.template($('#search_item-tpl').html());
        },

        render: function () {
            this.$el.html(this.tpl(this.model.attributes));
            return this;
        },

        logSearchItem: function(event) {
            event.preventDefault();
            var target = this.model.id;
            var link = $(event.target).attr('href');
            var collection = this.model.collection;
            var page = collection.page;
            var pageSize = collection.pageSize;
            var searchTerm = collection.searchTerm;
            var index = collection.indexOf(this.model);
            Logger.log("edx.course.search.result_selected",
                {
                    "search_term": searchTerm,
                    "result_position": (page * pageSize + index),
                    "result_link": target
                });
            window.location.href = link;
        }
    });

});

})(define || RequireJS.define);

